"""Repository foundations, and the SQL-injection boundary (spec section 57).

Everything that composes SQL in this application goes through the helpers here,
which is what makes the injection defence auditable: there is one file to read,
not a query surface spread across eight repositories.

THREE RULES, ENFORCED STRUCTURALLY

**Values are never formatted into SQL.** They travel as `%s` placeholders and
are bound by psycopg, which sends them out-of-band from the statement text. No
amount of quoting in a filter value can change the parsed shape of a query.

**Identifiers come from an allow-list, never from the request.** A sort field
cannot be a placeholder -- PostgreSQL will not accept a parameter where a column
name belongs -- so it has to be composed into the statement. The request
therefore never supplies a column name: it supplies a *key*, which is looked up
in a mapping this codebase owns. An unknown key is rejected with 422. A caller
sending `?sort_by=id; drop table x --` gets a validation error, because that
string is not a key in the map.

**Composition uses `psycopg.sql`, not f-strings.** Where an identifier genuinely
must be interpolated, `sql.Identifier` quotes and escapes it. `WhereBuilder`
accumulates fragments and their parameters together so the two cannot drift out
of step -- the classic way a parameterised query quietly becomes a concatenated
one.

`ruff`'s S608 rule flags f-string SQL, and the test suite feeds injection
payloads through every filter, sort and UUID parameter.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row


class SortDirection(str, Enum):
    """Sort direction. An enum, so only two values can ever reach the SQL."""

    ASC = "asc"
    DESC = "desc"


class UnknownSortFieldError(ValueError):
    """Raised when a sort key is not in the allow-list.

    Surfaced to the client as 422 with the permitted keys, so a legitimate
    caller can correct themselves and a malicious one learns nothing useful.
    """

    def __init__(self, field: str, allowed: list[str]) -> None:
        self.field = field
        self.allowed = allowed
        super().__init__(f"Unknown sort field. Permitted values: {', '.join(sorted(allowed))}.")


class SortSpec:
    """Maps request-facing sort keys to real columns.

    The mapping is the allow-list. Keys are the vocabulary the API exposes;
    values are `(table_alias, column)` pairs from this codebase. Nothing a
    client sends is ever used as a column name.
    """

    def __init__(self, mapping: dict[str, tuple[str, str]], default: str) -> None:
        if default not in mapping:
            raise ValueError(f"Default sort field {default!r} is not in the mapping.")
        self._mapping = mapping
        self._default = default

    @property
    def allowed(self) -> list[str]:
        return sorted(self._mapping)

    def resolve(
        self,
        field: str | None,
        direction: SortDirection | None = None,
    ) -> sql.Composed:
        """Build a validated ORDER BY clause.

        Raises:
            UnknownSortFieldError: If `field` is not an allow-listed key.
        """
        key = field or self._default
        if key not in self._mapping:
            raise UnknownSortFieldError(key, self.allowed)

        table, column = self._mapping[key]
        # `direction` is an enum, so only ASC or DESC can be produced here.
        order = sql.SQL("asc") if direction is SortDirection.ASC else sql.SQL("desc")

        return sql.SQL("order by {}.{} {}").format(
            sql.Identifier(table), sql.Identifier(column), order
        )


class WhereBuilder:
    """Accumulates WHERE conditions alongside their parameters.

    Keeping the fragment and its values together in one `add` call is the point:
    a builder that returned a string and expected the caller to assemble a
    matching parameter tuple separately is exactly how a mismatch turns into
    someone "fixing" it with string formatting.
    """

    def __init__(self) -> None:
        self._conditions: list[sql.Composable] = []
        self._params: list[Any] = []

    def add(self, condition: str, *params: Any) -> WhereBuilder:
        """Add a condition. `condition` is a literal fragment from this codebase.

        Every `%s` in the fragment must have a matching parameter.
        """
        if condition.count("%s") != len(params):
            raise ValueError(
                f"Condition {condition!r} has {condition.count('%s')} placeholders "
                f"but {len(params)} parameters were supplied."
            )
        self._conditions.append(sql.SQL(condition))
        self._params.extend(params)
        return self

    def add_if(self, value: Any, condition: str, *params: Any) -> WhereBuilder:
        """Add a condition only when `value` is not None.

        The common case: an optional filter that should not appear in the query
        at all when the caller omitted it.
        """
        if value is not None:
            self.add(condition, *params)
        return self

    @property
    def params(self) -> list[Any]:
        return list(self._params)

    def clause(self) -> sql.Composable:
        """Return the WHERE clause, or an empty fragment when unfiltered."""
        if not self._conditions:
            return sql.SQL("")
        joined = sql.SQL(" and ").join(self._conditions)
        return sql.SQL("where {}").format(joined)


class BaseRepository:
    """Shared query execution.

    Repositories hold database access only. Business rules and KPI formulas
    live in services (spec section 8), so nothing here interprets a result --
    it fetches rows and returns them.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def fetch_all(
        self,
        statement: sql.Composable | str,
        params: list[Any] | tuple[Any, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Run a query and return every row as a dict."""
        async with self._connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(statement, params)
            return list(await cursor.fetchall())

    async def fetch_one(
        self,
        statement: sql.Composable | str,
        params: list[Any] | tuple[Any, ...] | None = None,
    ) -> dict[str, Any] | None:
        """Run a query and return the first row, or None."""
        async with self._connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(statement, params)
            return await cursor.fetchone()

    async def fetch_value(
        self,
        statement: sql.Composable | str,
        params: list[Any] | tuple[Any, ...] | None = None,
        default: Any = None,
    ) -> Any:
        """Run a query and return the first column of the first row."""
        row = await self.fetch_one(statement, params)
        if not row:
            return default
        return next(iter(row.values()))

    async def count(
        self,
        from_clause: sql.Composable | str,
        where: WhereBuilder,
    ) -> int:
        """Count rows matching a filter, for pagination totals.

        A separate COUNT is used rather than a window function alongside the
        page. The window form reads the whole matching set to compute the total
        on every row; two statements let the paged query stop at LIMIT and let
        the count use an index-only scan.
        """
        statement = sql.SQL("select count(*) as total from {} {}").format(
            from_clause if isinstance(from_clause, sql.Composable) else sql.SQL(from_clause),
            where.clause(),
        )
        return int(await self.fetch_value(statement, where.params, default=0) or 0)
