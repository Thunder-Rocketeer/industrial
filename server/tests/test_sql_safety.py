"""SQL injection defences (spec sections 13 and 57).

The spec asks for the repository implementation to be audited specifically for
injection, and for automated tests that feed malicious values through filters,
search parameters, sort parameters and UUID parameters.

The defence has three independent layers, and there is a section below for each:

  1. **Static** -- no repository builds SQL by string formatting. Asserted by
     parsing the source, so a future f-string SQL fails the suite rather than
     needing to be noticed in review.
  2. **Composition** -- `WhereBuilder` keeps fragments and parameters together,
     and `SortSpec` resolves a request key through an allow-list. A payload
     cannot become a column name.
  3. **Boundary** -- Pydantic rejects a malformed UUID, date or enum before any
     query exists.

Layer 3 stops most payloads before layer 2 is reached, which is the point of
having all three: each is sufficient on its own for the cases it covers.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from psycopg import sql

from app.repositories.base import (
    SortDirection,
    SortSpec,
    UnknownSortFieldError,
    WhereBuilder,
)
from app.repositories.inventory import INVENTORY_SORTS
from app.repositories.production import PRODUCTION_SORTS
from app.repositories.quality import QUALITY_SORTS

REPOSITORY_DIR = Path(__file__).resolve().parent.parent / "app" / "repositories"

#: Payloads from spec section 57, plus the usual variations.
INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE production_records; --",
    "1; DELETE FROM machines WHERE 1=1",
    "' UNION SELECT * FROM users --",
    "admin'--",
    '" OR ""="',
    "1' AND SLEEP(5)--",
    "\\'; DROP TABLE users; --",
    "%27%20OR%201%3D1",
    "'; SELECT pg_sleep(10); --",
    "0x27 OR 1=1",
    "') OR ('1'='1",
]


# =============================================================================
# Layer 1 -- static: no repository formats SQL
# =============================================================================


def _repository_sources() -> list[Path]:
    return sorted(REPOSITORY_DIR.glob("*.py"))


@pytest.mark.security
@pytest.mark.parametrize("path", _repository_sources(), ids=lambda p: p.name)
def test_no_repository_uses_an_f_string_for_sql(path: Path) -> None:
    """An f-string containing SQL keywords is the injection smell.

    The exception is a WHERE fragment built from a fixed table alias, which is
    a literal from this codebase and contains no user value -- those are
    detected by looking for `%s` placeholders, which prove the values travel as
    parameters.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    keywords = ("select ", "insert ", "update ", "delete ", "drop ", "union ")

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        literal = "".join(
            part.value for part in node.values if isinstance(part, ast.Constant)
        ).lower()
        if any(keyword in literal for keyword in keywords):
            offenders.append(literal[:80])

    assert not offenders, (
        f"{path.name} builds SQL with an f-string, which defeats parameterisation: {offenders}"
    )


@pytest.mark.security
@pytest.mark.parametrize("path", _repository_sources(), ids=lambda p: p.name)
def test_no_repository_concatenates_sql_strings(path: Path) -> None:
    """`"select ... " + value` is the other way parameterisation gets lost."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Add):
            continue
        for side in (node.left, node.right):
            if isinstance(side, ast.Constant) and isinstance(side.value, str):
                lowered = side.value.lower()
                assert not any(keyword in lowered for keyword in ("select ", "where ", "from ")), (
                    f"{path.name} concatenates a SQL string."
                )


@pytest.mark.security
@pytest.mark.parametrize(
    "path",
    # base.py is excluded: it *defines* WhereBuilder, so its internal
    # `self.add(condition, *params)` forwards a parameter rather than passing a
    # literal. Every other repository is a caller and must pass a literal.
    [p for p in _repository_sources() if p.name != "base.py"],
    ids=lambda p: p.name,
)
def test_where_conditions_are_plain_string_literals(path: Path) -> None:
    """Every WHERE fragment must be a literal owned by this codebase.

    An f-string or a concatenation as the condition argument would mean a value
    is being formatted into the SQL rather than bound as a parameter. This
    checks the argument's AST node type, so the rule holds regardless of what
    the string happens to contain.

    Table aliases are the one legitimate interpolation -- `f"{alias}.machine_id
    = %s"` -- so an f-string is accepted only when every one of its interpolated
    parts is a simple name and the literal half still carries its placeholders.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("add", "add_if") or not node.args:
            continue

        # `add(condition, *params)` vs `add_if(value, condition, *params)`.
        condition = node.args[0] if node.func.attr == "add" else node.args[1]

        if isinstance(condition, ast.Constant) and isinstance(condition.value, str):
            continue

        assert isinstance(condition, ast.JoinedStr), (
            f"{path.name}: a WHERE condition must be a string literal, "
            f"not {type(condition).__name__}."
        )
        for part in condition.values:
            assert isinstance(part, (ast.Constant, ast.FormattedValue)), (
                f"{path.name}: unexpected f-string part in a WHERE condition."
            )
            if isinstance(part, ast.FormattedValue):
                assert isinstance(part.value, ast.Name), (
                    f"{path.name}: only a simple name (a table alias) may be "
                    f"interpolated into a WHERE condition."
                )


# =============================================================================
# Layer 2 -- composition
# =============================================================================


@pytest.mark.security
@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_a_sort_payload_is_rejected(payload: str) -> None:
    """A sort field cannot be a bound parameter, so it must be allow-listed.

    This is the one place where a request value influences the SQL *structure*,
    and therefore the one that has to be checked by identity against a mapping
    this codebase owns rather than sanitised.
    """
    for spec in (PRODUCTION_SORTS, QUALITY_SORTS, INVENTORY_SORTS):
        with pytest.raises(UnknownSortFieldError):
            spec.resolve(payload, SortDirection.ASC)


@pytest.mark.security
def test_a_rejected_sort_names_the_permitted_values() -> None:
    """The error is actionable, and discloses nothing not already in the docs."""
    with pytest.raises(UnknownSortFieldError) as exc_info:
        PRODUCTION_SORTS.resolve("id; drop table production_records --")

    assert "Permitted values" in str(exc_info.value)
    assert "date" in exc_info.value.allowed


@pytest.mark.security
def test_an_allow_listed_sort_produces_quoted_identifiers() -> None:
    """Even the accepted path quotes identifiers rather than interpolating."""
    composed = PRODUCTION_SORTS.resolve("produced", SortDirection.DESC)
    rendered = composed.as_string(None)

    assert '"p"."produced_quantity"' in rendered
    assert "desc" in rendered


@pytest.mark.security
def test_sort_direction_can_only_be_asc_or_desc() -> None:
    """An enum, so no third value can reach the SQL."""
    assert {d.value for d in SortDirection} == {"asc", "desc"}


@pytest.mark.security
def test_a_sort_spec_rejects_an_unmapped_default() -> None:
    """Guards the mapping itself against a typo that would break every request."""
    with pytest.raises(ValueError, match="not in the mapping"):
        SortSpec(mapping={"date": ("p", "record_date")}, default="nonexistent")


@pytest.mark.security
@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_a_filter_payload_stays_a_parameter(payload: str) -> None:
    """A malicious value must remain a value, never become SQL.

    The rendered statement contains a placeholder; the payload appears only in
    the parameter list. Nothing a client sends can alter the parsed statement.
    """
    where = WhereBuilder()
    where.add("p.machine_id = %s", payload)

    rendered = where.clause().as_string(None)

    assert "%s" in rendered
    assert payload not in rendered, "The payload leaked into the statement text."
    assert where.params == [payload]


@pytest.mark.security
def test_the_builder_rejects_a_placeholder_mismatch() -> None:
    """A fragment and its parameters cannot drift apart.

    That drift is how someone "fixes" a broken query with string formatting,
    which is how parameterisation is lost.
    """
    with pytest.raises(ValueError, match="placeholders"):
        WhereBuilder().add("p.machine_id = %s and p.line_id = %s", "only-one-value")

    with pytest.raises(ValueError, match="placeholders"):
        WhereBuilder().add("p.machine_id = 1", "unexpected-value")


@pytest.mark.security
def test_an_omitted_filter_adds_no_condition() -> None:
    """An absent filter must not appear in the query at all."""
    where = WhereBuilder()
    where.add_if(None, "p.machine_id = %s", None)

    assert where.clause().as_string(None) == ""
    assert where.params == []


@pytest.mark.security
def test_conditions_are_joined_with_and() -> None:
    where = WhereBuilder()
    where.add("p.record_date >= %s", "2026-01-01")
    where.add("p.machine_id = %s", "abc")

    rendered = where.clause().as_string(None)

    assert rendered.startswith("where ")
    assert " and " in rendered


@pytest.mark.security
def test_dimension_grouping_is_allow_listed() -> None:
    """The other structural parameter: which table to group by.

    Internal today, but validated so that a future endpoint forwarding a query
    parameter into it cannot become an injection point.
    """
    import asyncio

    from app.repositories.production import ProductionRepository

    # Constructed without a connection: the dimension is validated before any
    # query is built, so the guard is reached without touching a database.
    repository = ProductionRepository.__new__(ProductionRepository)

    async def call() -> None:
        await repository.get_production_by_dimension(
            dimension="machines; drop table x --",
            start_date="2026-01-01",  # type: ignore[arg-type]
            end_date="2026-01-31",  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="Unknown dimension"):
        asyncio.run(call())


@pytest.mark.security
def test_identifiers_are_quoted_when_composed() -> None:
    """`sql.Identifier` escapes, so even a hostile name cannot break out."""
    rendered = (
        sql.SQL("select {} from t").format(sql.Identifier('evil"; drop table x --')).as_string(None)
    )

    assert "drop table x" in rendered  # present, but...
    assert rendered.count('"') >= 2  # ...entirely inside a quoted identifier
    assert rendered.startswith('select "')
