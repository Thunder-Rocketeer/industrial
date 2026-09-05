# Database

Reference for the Supabase PostgreSQL schema, its security posture, and the
deterministic seed. Built in Phase 2 against spec sections 6, 7, 11, 29, 30, 31
and 66.

- **15 tables**, 25 foreign keys, 58 CHECK constraints, 20 unique constraints,
  28 indexes, 10 enum types
- **~13,200 seeded rows**, deterministic and re-runnable
- **Deny-by-default RLS** on every table

---

## 1. Applying the schema

The migrations in `supabase/migrations/` are the source of truth. Pick whichever
path matches your tooling; both produce the same database.

### Option A — Supabase dashboard (no CLI needed)

1. Open your project at [supabase.com](https://supabase.com) → **SQL Editor**.
2. Paste the contents of **`supabase/schema.sql`** and run it.

`schema.sql` is generated from the migrations and wraps them in a single
transaction, so a failure anywhere leaves the database untouched rather than
half-migrated. Regenerate it after changing any migration:

```bash
cd server
python tools/build_schema.py           # rewrite it
python tools/build_schema.py --check   # verify it is current (CI-friendly)
```

### Option B — Supabase CLI

```bash
supabase link --project-ref <your-project-ref>
supabase db push
```

### Option C — psql

```bash
psql "$DATABASE_URL" -f supabase/schema.sql
```

### Then seed and verify

```bash
cd server
python -m app.db.seed      # write the demo dataset
python -m app.db.verify    # check the result
```

---

## 2. Migrations

Applied in filename order. The 14-digit prefix makes that order explicit rather
than incidental.

| File | Contents |
|---|---|
| `20260101000100_schema_and_helpers.sql` | `app` schema, `set_updated_at`, `prevent_mutation`, RBAC helper functions |
| `20260101000200_enums.sql` | 10 enum types |
| `20260101000300_reference_tables.sql` | roles, users, factory_lines, components, shifts, machines, defects |
| `20260101000400_production_tables.sql` | production_records, quality_records, daily_targets |
| `20260101000500_inventory_tables.sql` | inventory_items, inventory_transactions |
| `20260101000600_maintenance_alerts_audit.sql` | maintenance_records, alerts, audit_logs |
| `20260101000700_indexes.sql` | 28 indexes |
| `20260101000800_row_level_security.sql` | RLS, privilege revocation, audit policy |

---

## 3. Entity relationships

```
roles ──< users ──────────────────< audit_logs
                 └───────────────< alerts.acknowledged_by
                 └───────────────< inventory_transactions.created_by

factory_lines ──< components ──┐
              ──< machines ────┤
              ──< daily_targets┘
              ──< alerts

machines ──< production_records >── components
                    ^                    ^
              shifts┘                    │
                    │                    │
                    └──< quality_records ┘
                              │
                          defects

machines ──< maintenance_records
components ──< inventory_items ──< inventory_transactions
```

Every relationship in the spec's list is present. None were added beyond it
except the two denormalised paths described in §4, which exist for query
performance and are constrained so they cannot drift.

---

## 4. Two design decisions worth knowing

### 4.1 Denormalisation held true by composite foreign keys

`production_records` stores `line_id`, and `quality_records` stores `machine_id`
and `component_id`. Both are derivable by a join, so both are redundant in the
normalisation sense.

They are stored because the dashboard filters and groups by line, machine and
component on nearly every query (spec §5.2), and because spec §29 explicitly
calls for indexes on `quality_records(machine_id)` and
`quality_records(component_id)` — which requires those columns to exist.

The usual objection to denormalisation is drift. That is prevented structurally
rather than by discipline:

```sql
-- machines carries a redundant-looking UNIQUE (id, line_id) ...
constraint machines_id_line_id_key unique (id, line_id)

-- ... purely so production_records can point at it as a pair:
constraint production_records_machine_line_fkey
  foreign key (machine_id, line_id) references public.machines (id, line_id)
```

PostgreSQL now rejects any production row whose `line_id` disagrees with its
machine's actual line. The same pattern ties `quality_records` to its parent
production record. No trigger, no application check, no possibility of drift.

### 4.2 `inventory_items.status` is generated, not stored

```sql
status public.inventory_status generated always as (
  case
    when current_quantity <= minimum_stock then 'CRITICAL'
    when current_quantity <= reorder_point then 'LOW'
    when current_quantity >= maximum_stock then 'OVERSTOCKED'
    else 'HEALTHY'
  end
) stored
```

Stock health is a pure function of the quantity against its thresholds, so
deriving it eliminates the class of bug where the number and its label disagree.
There is no code path that can write an inconsistent status and no job needed to
refresh one. Being `STORED`, it indexes normally, which spec §29 requires.

The arm order matters: a quantity at or below `minimum_stock` is CRITICAL even
though it is also at or below `reorder_point`. The
`inventory_items_threshold_order_check` constraint enforces
`minimum <= reorder < maximum`, without which the ladder would be incoherent.

This is data integrity, not a KPI. Aggregate calculations stay in backend
services per spec §42.

---

## 5. Table reference

### roles
RBAC catalogue (spec §56). Six rows: `ADMIN`, `FACTORY_MANAGER`,
`PRODUCTION_SUPERVISOR`, `QUALITY_ENGINEER`, `INVENTORY_MANAGER`, `VIEWER`.
`rank` orders them for display; authorization decisions are made by the backend
policy module, never by comparing ranks.

### users
**There is no password column.** Authentication is Google OAuth 2.0 / OIDC
(spec §54), so no credential is ever stored, and "do not store plaintext
passwords" is satisfied structurally rather than by convention.

`google_sub` holds the OIDC `sub` claim — the only Google identifier guaranteed
stable for a user. Email is a lookup key, never the identity, because an address
can be reassigned within a Workspace domain. Seeded users have `google_sub =
NULL`; the OAuth flow attaches it on first sign-in.

### factory_lines, components, shifts, machines, defects
Reference data. Each carries a human-meaningful `code` alongside its UUID, with
a format CHECK (`^LINE-[A-Z]$`, `^[A-Z]{2,4}-[A-Z]{1,3}-[0-9]{3}$`, …). The seed
derives every UUID from that code, which is what makes re-seeding idempotent.

`shifts.planned_minutes` is the OEE Availability denominator.
`components.ideal_cycle_time_seconds` is the OEE Performance denominator. Both
live with the entity rather than being hard-coded in a service (spec §42).

`shifts.end_time` may precede `start_time`: the night shift wraps past midnight,
so no ordering constraint is imposed.

### production_records
**Grain: (record_date, shift_id, machine_id, component_id)** — declared as a
UNIQUE constraint, which both states the grain and gives the seed its
`ON CONFLICT` target.

Key constraints:
- `accepted + rejected = produced` — nothing vanishes
- `operating_minutes <= planned_minutes`, `downtime_minutes <= planned_minutes`
- `produced_quantity = 0 OR operating_minutes > 0` — nothing is made in no time
- `ended_at > started_at`

### quality_records
**Grain: (production_record_id, defect_id)**, with two legal row shapes:

| Row | `defect_id` | `passed` | `rejected` | Meaning |
|---|---|---|---|---|
| Pass line | `NULL` | > 0 | 0 | Units that passed. Exactly one per production record. |
| Rejection line | set | 0 | > 0 | Units rejected for that one defect type. Zero or more. |

`quality_records_defect_shape_check` enforces exactly those two shapes.

The consequence is that `SUM(inspected_quantity)` over a production record
equals its `produced_quantity`, defect rate is a plain ratio, and a Pareto chart
is `GROUP BY defect_id ORDER BY SUM(rejected_quantity) DESC` with no
post-processing. The obvious alternative — one row per production record naming a
"primary defect" — would discard every secondary defect and make the Pareto
chart quietly wrong.

`UNIQUE NULLS NOT DISTINCT (production_record_id, defect_id)` enforces "at most
one pass line" and serves as the seed's conflict target. **Requires PostgreSQL
15+**; Supabase runs 15 or later.

### inventory_items, inventory_transactions
Stock movements are **signed**: `quantity_delta` is positive for anything adding
stock, negative for anything removing it. Running balances are therefore a plain
`SUM` with no `CASE` over the type, and
`inventory_transactions_delta_sign_check` ties the sign to the movement type so
a `RECEIPT` cannot reduce stock. `balance_after` is carried so the inventory
trend chart is one indexed read rather than a window function over the ledger.

### maintenance_records, alerts
Both use a CHECK to keep status and timestamps telling the same story — completed
work has both timestamps, scheduled work has neither; an OPEN alert has no
acknowledgement.

`alerts.dedupe_key` is UNIQUE, so re-raising the same condition updates the
existing row instead of filling the panel with duplicates.
`alerts_has_subject_check` requires at least one of machine, component,
inventory item or line, so an alert can never be about nothing.
`description` is required and non-blank, because spec §45 requires state to be
readable as text rather than conveyed by colour or icon alone.

### audit_logs
Append-only, enforced by a `BEFORE UPDATE OR DELETE` trigger that rejects the
operation for **every** caller including service-role. An audit trail the
application can rewrite proves nothing.

The primary key is a `bigint` identity, not a UUID. This is the one table where
insert order carries meaning and volume is highest; a monotonic key keeps index
writes append-only. Spec §6 asks for UUIDs "where practical" — here a sequence
is the better fit.

> **Known limitation:** the trigger blocks `UPDATE` and `DELETE` but not
> `TRUNCATE`, which fires only statement-level triggers. `TRUNCATE` requires
> table-owner privilege, so this is not reachable by the application, and the
> seed's `--truncate` reset depends on it. If the audit trail ever needs to be
> tamper-evident against a privileged operator, that requires append-only
> storage outside PostgreSQL, not a stronger trigger.

---

## 6. Security

### 6.1 RLS: deny by default

Every request reaches the database through FastAPI using the service-role key.
No browser ever holds a Supabase credential (spec §66). The correct RLS
configuration for that architecture is not a set of permissive policies — it is
the deliberate absence of them.

Three independent layers:

1. **RLS enabled** on all 15 tables. With no permissive policy, PostgreSQL
   denies all access to any role subject to RLS.
2. **RLS forced** (`FORCE ROW LEVEL SECURITY`), so the table owner is subject to
   it too. Without `FORCE`, an owner-privileged connection silently bypasses
   every policy.
3. **Privileges revoked** from `anon` and `authenticated`, with
   `ALTER DEFAULT PRIVILEGES` so future tables inherit the same. Even if a
   policy were added by mistake, the grant it would need does not exist.

The backend's `service_role` holds `BYPASSRLS`, which takes precedence over
`FORCE`, so the API works normally. Authorization for those requests is decided
in the backend RBAC policy module (spec §56).

The one **enforced** rule rather than an absence is on `audit_logs`: a
`RESTRICTIVE` policy that `ANDs` with any future permissive policy, so mutation
cannot be re-opened by accident.

### 6.2 Operations requiring privileged backend access

Everything. There is no unprivileged path to any table. Specifically:

| Operation | Credential | Notes |
|---|---|---|
| All reads and writes | `SUPABASE_SERVICE_ROLE_KEY` or `DATABASE_URL` | Backend only |
| Applying migrations | Project owner / `postgres` | One-time setup |
| Running the seed | `DATABASE_URL` | Development only |
| `--truncate` reset | `DATABASE_URL`, table owner | Refused when `APP_ENV=production` |
| Reading `audit_logs` | service-role | Mutation blocked for everyone |

**The service-role key bypasses RLS entirely.** It must never appear in
`client/`, in any `NEXT_PUBLIC_*` variable, or in a browser response.

### 6.3 SQL injection

No user-supplied value is ever concatenated into SQL. The seed builds statements
from column names that originate in this codebase, quoted as identifiers; the
verifier's table names come from its own module constants. From Phase 3,
repositories use parameterised queries throughout, with sort and filter fields
resolved through explicit allow-list maps (spec §57).

### 6.4 Function hardening

All five helper functions are declared `SET search_path = ''` and reference
objects by fully qualified name. Without that, a caller can prepend a schema to
`search_path` and shadow a referenced object — a genuine privilege-escalation
route that Supabase's own security advisor flags. A test asserts this from the
parse tree.

---

## 7. Indexes

28 indexes, chosen against the queries the dashboard actually runs. Spec §29
warns against indexing every column; two rules kept the list honest.

**Composite over single-column where the access is compound.** Production and
quality queries bound a date range first, then group by machine, component or
line. `(machine_id, record_date DESC)` serves both "this machine over this
period" and "this machine, most recent first". A leading column also satisfies
queries filtering on it alone, so the single-column index would be redundant.

**Nothing PostgreSQL already provides.** A PRIMARY KEY or UNIQUE constraint
creates its own index, so the production grain key is not duplicated here.

| Table | Indexes |
|---|---|
| `production_records` | `record_date`, `(machine_id, record_date)`, `(component_id, record_date)`, `(line_id, record_date)`, `(shift_id, record_date)` |
| `quality_records` | `inspected_at`, `(machine_id, inspected_at)`, `(component_id, inspected_at)`, `(defect_id, inspected_at)` **partial**, `production_record_id` |
| `machines` | `status`, `(line_id, status)`, `next_maintenance_date` **partial** |
| `inventory_items` | `status`, `component_id` **partial**, `(status, name)` **partial** |
| `inventory_transactions` | `(inventory_item_id, occurred_at)` |
| `maintenance_records` | `(machine_id, scheduled_date)`, `(status, scheduled_date)` |
| `alerts` | `(severity, triggered_at)` **partial on OPEN**, `(status, triggered_at)`, `machine_id` **partial** |
| `daily_targets` | `(component_id, target_date)` |
| `users` | `role_id` |
| `audit_logs` | `occurred_at`, `(actor_user_id, occurred_at)`, `(resource_type, resource_id, occurred_at)`, seed key **partial unique** |

Five are **partial**. The alerts panel reads only open alerts and the Pareto
chart only rejection lines, so indexing just those rows keeps each query's cost
independent of total table size.

---

## 8. The seed

```bash
cd server
python -m app.db.seed                          # default: 90 days, seed from .env
python -m app.db.seed --dry-run                # generate and report, write nothing
python -m app.db.seed --history-days 30
python -m app.db.seed --seed 12345
python -m app.db.seed --reference-date 2026-09-05
python -m app.db.seed --truncate               # reset first (destructive)
```

### 8.1 Architecture

```
reference_data.py   the fixed factory: lines, machines, components,
                    shifts, defects, materials, roles, demo users
        |
generator.py        deterministic row generation. No database code at all.
        |
seed.py             upserts the rows. No generation logic at all.
```

The split is what makes the data testable: determinism, referential integrity,
quantity arithmetic and the realism properties are all verified without a
database. It also guarantees spec §31's "do not make values random on every API
request" structurally — nothing in the generator runs in a request path.

### 8.2 Determinism

Two mechanisms, doing different jobs.

**Identifiers** come from `uuid5(SEED_NAMESPACE, "entity|natural-key")`. The same
natural key always yields the same UUID, in any process, on any machine. That is
what makes every write a plain `ON CONFLICT (id) DO UPDATE` with no lookup table
and no pre-existing parent row — a foreign key can be computed before the row it
points at is inserted. It is also why the generator can build production records
*before* machines, and derive machine utilisation from them.

> Changing `SEED_NAMESPACE` changes every seeded ID, which would orphan an
> existing database rather than update it. A test pins the value.

**Values** come from `random.Random` seeded by `stable_seed()`, which hashes with
blake2b. Python's built-in `hash()` is deliberately not used: it is salted per
process for strings, so a "deterministic" seed built on it would produce
different data on every run.

Each draw is keyed to the *coordinates of the thing being generated* — the date,
shift and machine — rather than drawn from one shared stream. Generation is
therefore order-independent: adding a machine changes only that machine's rows.
A single shared stream would reshuffle the entire history whenever the catalogue
changed.

### 8.3 Idempotency

| Table | Conflict target | Behaviour on re-run |
|---|---|---|
| All except `audit_logs` | `id` (derived) | `DO UPDATE` — rows refreshed in place |
| `audit_logs` | partial unique index on `metadata->>'seed_key'` | `DO NOTHING` — append-only preserved |

There is no "delete everything first" step, so a re-seed never leaves the
database briefly empty, and rows the application added alongside seeded ones are
untouched. The whole seed runs in **one transaction**: an interrupted run cannot
leave half a factory behind.

### 8.4 What gets generated

Row counts for the default 90-day window:

| Table | Rows |
|---|---|
| roles | 6 |
| users | 6 |
| factory_lines | 4 |
| shifts | 3 |
| components | 10 |
| defects | 8 |
| machines | 14 |
| production_records | ~3,070 |
| quality_records | ~8,620 |
| daily_targets | ~760 |
| inventory_items | 8 |
| inventory_transactions | ~660 |
| maintenance_records | 45 |
| alerts | 10 |
| audit_logs | 7 |
| **Total** | **~13,200** |

Exact counts shift slightly with the reference date, since the number of working
days in the window changes.

### 8.5 Realism model (spec §31)

The data is shaped by **fixed effects**, not noise. Every one of these is
asserted by a test.

| Property | Implementation |
|---|---|
| Plant closed Sundays, reduced Saturdays | `_day_output_factor` |
| Morning starts slowly, evening peaks, night lighter | `ShiftSpec.output_factor` — 0.94 / 1.00 / 0.83 |
| Some machines consistently better | `MachineSpec.efficiency` — 0.86 to 1.06, fixed per machine |
| Less reliable machines stop more | `MachineSpec.reliability` — drives downtime probability |
| A defect spike on one component | Steering Knuckle, days 17–25 ago, ×3.4 |
| Inventory declines between replenishments | Ledger walked backwards from current stock |
| Targets are a stretch | 1.02–1.09 × the achievable plan, so achievement lands ~85–95% |

The **defect distribution is deliberately skewed** so the Pareto chart shows a
real 80/20 shape rather than eight equal bars:

| Defect | Share |
|---|---|
| Dimensional Out-of-Tolerance | 26.8% |
| Surface Defect | 21.6% |
| Burr | 15.7% |
| Crack | 10.9% |
| Thread Damage | 8.5% |
| Incorrect Assembly | 6.0% |
| Material Defect | 6.0% |
| Heat Treatment Failure | 4.4% |

Top three: **64%**.

**Machine utilisation is derived from the generated history**, not invented, so
the machines board agrees with the production module:

| Status | Utilisation |
|---|---|
| RUNNING (9 machines) | 91–100% |
| IDLE (2) | 87–91% |
| MAINTENANCE (2) | 65–71% |
| OFFLINE (1) | 53% |

The denominator is every minute the plant was scheduled to run, not only the
shifts a machine worked — otherwise a machine idle all week would report full
utilisation, because an idle shift produces no record and its wasted time would
be missing from both sides of the ratio.

**Inventory covers all four states**, with two items CRITICAL so the alerts
panel has real content on first load:

| SKU | State |
|---|---|
| Bearing Assemblies, Lubricant | CRITICAL |
| Aluminium Alloy, Cutting Inserts | LOW |
| Steel Billets, Cast Iron, Packaging | HEALTHY |
| Fasteners | OVERSTOCKED |

The ledger is walked **backwards** from each item's stated quantity, so the final
balance equals it exactly. Generating forwards from a guessed opening balance
would drift, and the CRITICAL items the alerts panel depends on would stop being
critical.

**Alerts are derived from the seeded state**, not invented independently: every
critical-inventory alert names a genuinely critical item, and every offline
alert names a genuinely offline machine. A user who follows an alert to its
module finds the situation it describes.

### 8.6 Reset

```bash
cd server
python -m app.db.seed --truncate
```

`TRUNCATE ... RESTART IDENTITY CASCADE` on all 15 tables, then a normal seed.
Refused when `APP_ENV=production`.

For a full rebuild, re-run `supabase/schema.sql` against an empty database and
seed again.

---

## 9. Verification

```bash
cd server
python -m app.db.verify
```

Eleven checks against the live database, exiting non-zero on any failure:

| # | Check |
|---|---|
| 1 | All 15 tables exist |
| 2 | Row counts meet the spec minimums |
| 3 | Foreign key constraints are declared on every child table |
| 4 | Denormalised columns agree with their source |
| 5 | All 28 named indexes exist |
| 6 | RLS enabled **and forced** on every table |
| 7 | `anon` and `authenticated` hold no privileges |
| 8 | `audit_logs` genuinely rejects an `UPDATE` (behavioural, in a rolled-back savepoint) |
| 9 | Derived inventory status matches its definition |
| 10 | Inspections reconcile with production |
| 11 | Dashboard KPI queries return values in plausible ranges |

Check 11 runs the aggregate shapes Phase 3 services will use — 30-day production
and defect rate, defect Pareto, machine status spread, open alerts, target
achievement — and fails if any lands outside a believable range. That proves the
seeded data can actually answer the questions in spec §3, not merely that it is
non-null.

### Static validation, without a database

```bash
cd server
python tools/validate_sql.py    # parse migrations with the PostgreSQL grammar
pytest tests/test_migrations.py # schema structure assertions
pytest tests/test_seed_data.py  # 45 data-property assertions
pytest tests/test_seed_sql.py   # generated upsert statements
```

`pglast` wraps libpg_query — the parser PostgreSQL itself uses — so a file that
parses is valid PostgreSQL. This matters because the migrations run against a
hosted Supabase project rather than from the test suite; without it a syntax
error would only surface when someone applied the schema for real.

Parsing is not executing. It proves grammar and structure, not that a constraint
behaves as intended. That is what `app/db/verify.py` is for.

---

## 10. Demo accounts

Seeded per spec §50. **These are not credentials** — the schema has no password
column. Each row becomes a usable login only when someone signs in through
Google with the matching address, at which point the OAuth flow (Phase 3)
attaches the Google subject claim.

| Email | Name | Role |
|---|---|---|
| `admin@factory.local` | Priya Raghavan | Admin |
| `manager@factory.local` | Daniel Okonkwo | Factory Manager |
| `supervisor@factory.local` | Mei-Ling Chen | Production Supervisor |
| `quality@factory.local` | Tomas Novak | Quality Engineer |
| `inventory@factory.local` | Aisha Bello | Inventory Manager |
| `viewer@factory.local` | Jordan Whitfield | Viewer |

`.local` is a reserved TLD, so these can never resolve to real mailboxes. In a
deployed demo, replace them with addresses in a domain you control that Google
can actually authenticate.

---

## 11. Assumptions

Documented because they are judgement calls, not facts derived from the spec.

| Assumption | Rationale |
|---|---|
| One production record per machine per component per shift | Gives a clean grain and a natural idempotency key. A machine running the same part twice in a shift would need a sequence column. |
| Sunday is a full plant shutdown; Saturday runs at 72% | Makes the weekly pattern visible in trend charts. Real plants vary. |
| Shift planned minutes exclude breaks (450/450/420) | These are the OEE Availability denominators. |
| A defect is attributed to the machine that produced the part | Real attribution may involve upstream processes; the schema can express that, the seed does not model it. |
| `first_pass_quantity` is tracked only on the pass line | FPY counts units passing without rework; rejected units never had a first pass. |
| Ideal cycle times are plausible but invented | Real values would come from the machine tooling data. |
| Inventory consumption is independent of actual production volume | Keeps the ledger deterministic and simple. Tying it to production output would be more realistic and is a reasonable future enhancement. |
| Alerts are seeded as static rows | Phase 3 introduces the service that raises them from live conditions; `dedupe_key` is already in place for that. |
