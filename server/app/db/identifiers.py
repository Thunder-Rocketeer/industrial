"""Deterministic UUID derivation for seed data.

The seed must be re-runnable without creating duplicates (spec section 30,
requirement 4). The usual approaches are to keep a mapping table of natural key
to generated UUID, or to look up existing rows before every insert. Both add
state and round-trips.

Instead, every seeded row's primary key is derived from its natural key with
UUID version 5, which is a SHA-1 hash of a namespace plus a name. The same
natural key always yields the same UUID, on any machine, in any process. That
turns every insert into a plain `ON CONFLICT (id) DO UPDATE` upsert:

  * re-running the seed rewrites the same rows rather than adding new ones
  * foreign keys can be computed without having inserted the parent first, so
    related rows can be generated in any order and batched freely
  * the generated dataset can be compared across runs, which is what makes the
    determinism tests possible without a database

The namespace UUID below is a fixed, arbitrary constant for this project. It
must never change: changing it changes every seeded ID, which would orphan an
existing seeded database rather than update it.
"""

from __future__ import annotations

import uuid

# Project namespace. Generated once; treat as a constant of the schema.
SEED_NAMESPACE = uuid.UUID("7f4d2c18-3b9a-5e64-9d21-8a6c0f5b1e73")


def derive_id(entity: str, *natural_key_parts: object) -> uuid.UUID:
    """Derive a stable UUID for `entity` from its natural key.

    Args:
        entity: Table or logical entity name, for example ``"machine"``. Keeps
            the keyspaces of different tables from colliding when they share a
            natural key.
        natural_key_parts: The values that uniquely identify the row. Rendered
            with ``str()`` and joined, so ``date(2026, 1, 5)`` and
            ``"2026-01-05"`` produce the same identifier.

    Returns:
        A version 5 UUID that is identical for identical inputs.

    Raises:
        ValueError: If no natural key parts are supplied, which would make every
            row of that entity share one identifier.
    """
    if not natural_key_parts:
        raise ValueError(f"A natural key is required to derive an id for {entity!r}.")

    name = entity + "|" + "|".join(str(part) for part in natural_key_parts)
    return uuid.uuid5(SEED_NAMESPACE, name)
