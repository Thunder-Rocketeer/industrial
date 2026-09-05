-- =============================================================================
-- Migration 005 — inventory
--
--   inventory_items -> inventory_transactions
--   components      -> inventory_items (optional; raw materials have no part)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- inventory_items — raw materials and consumables (spec section 5.4)
--
-- `status` is a GENERATED column rather than a stored value. Stock health is a
-- pure function of the quantity against its thresholds, so deriving it removes
-- the entire class of bug where the number and the label disagree -- there is
-- no code path that can write an inconsistent status, and no background job is
-- needed to keep it fresh. It is a stored generated column, so it indexes
-- normally, which spec section 29 asks for.
--
-- Order of the CASE arms matters: a quantity at or below minimum_stock is
-- CRITICAL even though it is also at or below reorder_point.
--
-- This is data integrity, not a KPI. Aggregate calculations stay in backend
-- services per spec section 42; what lives here is the invariant that a row
-- describing 3 units of a material with a minimum of 50 is never labelled
-- healthy.
-- -----------------------------------------------------------------------------
create table public.inventory_items (
  id           uuid primary key default gen_random_uuid(),
  sku          text not null,
  name         text not null,
  material_type text not null,
  -- Set when the item is a finished/semi-finished part tracked as a component.
  -- NULL for raw materials such as steel billets, which are not components.
  component_id uuid,

  unit         text not null,
  current_quantity numeric(14, 3) not null,
  minimum_stock    numeric(14, 3) not null,
  reorder_point    numeric(14, 3) not null,
  maximum_stock    numeric(14, 3) not null,

  supplier_name           text not null default '',
  supplier_lead_time_days smallint,
  unit_cost               numeric(12, 2),

  status public.inventory_status
    generated always as (
      case
        when current_quantity <= minimum_stock then 'CRITICAL'::public.inventory_status
        when current_quantity <= reorder_point then 'LOW'::public.inventory_status
        when current_quantity >= maximum_stock then 'OVERSTOCKED'::public.inventory_status
        else 'HEALTHY'::public.inventory_status
      end
    ) stored,

  last_counted_at timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  constraint inventory_items_component_id_fkey
    foreign key (component_id) references public.components (id)
    on delete set null,

  constraint inventory_items_sku_key unique (sku),
  constraint inventory_items_sku_format_check
    check (sku ~ '^[A-Z][A-Z0-9-]{2,23}$'),
  constraint inventory_items_quantities_non_negative_check
    check (
      current_quantity >= 0 and
      minimum_stock    >= 0 and
      reorder_point    >= 0 and
      maximum_stock    >  0
    ),
  -- The thresholds must describe a coherent ladder, or `status` is meaningless.
  constraint inventory_items_threshold_order_check
    check (minimum_stock <= reorder_point and reorder_point < maximum_stock),
  constraint inventory_items_lead_time_range_check
    check (supplier_lead_time_days is null or supplier_lead_time_days between 0 and 365),
  constraint inventory_items_unit_cost_non_negative_check
    check (unit_cost is null or unit_cost >= 0),
  constraint inventory_items_name_not_blank_check
    check (length(btrim(name)) > 0)
);

comment on column public.inventory_items.status is
  'Derived, never written. CRITICAL at or below minimum, LOW at or below reorder point, OVERSTOCKED at or above maximum, otherwise HEALTHY.';
comment on constraint inventory_items_threshold_order_check on public.inventory_items is
  'minimum <= reorder < maximum. Without this ladder the generated status column would be incoherent.';

create trigger inventory_items_set_updated_at
  before update on public.inventory_items
  for each row execute function app.set_updated_at();


-- -----------------------------------------------------------------------------
-- inventory_transactions — the stock movement ledger
--
-- Movements are signed: `quantity_delta` is positive for anything that adds
-- stock and negative for anything that removes it. A single signed column
-- means running balances are a plain SUM with no CASE over the type, and the
-- CHECK below ties the sign to the movement type so the two cannot contradict
-- each other.
--
-- `balance_after` is the running balance at the time of the movement, kept so
-- the inventory trend chart is a single indexed read rather than a window
-- function over the whole ledger.
-- -----------------------------------------------------------------------------
create table public.inventory_transactions (
  id                uuid not null default gen_random_uuid(),
  inventory_item_id uuid not null,
  transaction_type  public.inventory_transaction_type not null,
  quantity_delta    numeric(14, 3) not null,
  balance_after     numeric(14, 3) not null,
  reference         text not null default '',
  notes             text not null default '',
  occurred_at       timestamptz not null,
  created_by        uuid,
  created_at        timestamptz not null default now(),

  constraint inventory_transactions_pkey primary key (id),
  constraint inventory_transactions_item_id_fkey
    foreign key (inventory_item_id) references public.inventory_items (id)
    on delete cascade,
  constraint inventory_transactions_created_by_fkey
    foreign key (created_by) references public.users (id)
    on delete set null,

  -- A movement of zero is not a movement.
  constraint inventory_transactions_delta_non_zero_check
    check (quantity_delta <> 0),
  constraint inventory_transactions_balance_non_negative_check
    check (balance_after >= 0),
  -- The sign must agree with the movement type. ADJUSTMENT may go either way.
  constraint inventory_transactions_delta_sign_check
    check (
      case transaction_type
        when 'RECEIPT'    then quantity_delta > 0
        when 'RETURN'     then quantity_delta > 0
        when 'ISSUE'      then quantity_delta < 0
        when 'SCRAP'      then quantity_delta < 0
        when 'ADJUSTMENT' then true
      end
    ),
  -- Idempotency key for the seed: one movement per item per reference.
  constraint inventory_transactions_item_reference_key
    unique (inventory_item_id, reference)
);

comment on table public.inventory_transactions is
  'Signed stock movement ledger. Positive delta adds stock, negative removes it.';
comment on constraint inventory_transactions_delta_sign_check on public.inventory_transactions is
  'Ties the sign of quantity_delta to the movement type so a RECEIPT cannot reduce stock.';
