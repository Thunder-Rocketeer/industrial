# Dashboard UI

How the interface is put together: the shell, the component vocabulary, the
responsive rules, the accessibility contract, and the conventions a new page
should follow.

Phase 6 built this on top of the Phase 5 data layer. It adds no data access of
its own — see [`frontend-data-layer.md`](./frontend-data-layer.md) for that.

---

## 1. Structure

```
app/
├── login/page.tsx              public
└── (app)/                      authenticated route group
    ├── layout.tsx              RequireAuth + AppShell   (Server Component)
    ├── dashboard/              executive overview
    ├── production/             output vs plan and target
    ├── quality/                defects, FPY, Pareto
    ├── inventory/              stock levels and alerts
    ├── machines/               fleet, and [machineId]/ detail
    ├── analytics/              OEE, efficiency, downtime
    ├── alerts/                 alert history
    └── maintenance/            scheduled and completed work
```

Every route follows the same two-file shape:

| File | Kind | Holds |
| --- | --- | --- |
| `page.tsx` | Server Component | `metadata`, a Suspense boundary, mounts the view |
| `XxxView.tsx` | Client Component | Hooks, filters, layout |

The split is what keeps the client boundary narrow (spec section 35). The route
itself ships no client JavaScript; the boundary begins at the view, which is the
first thing that genuinely needs state.

**The Suspense boundary is required, not stylistic.** Any component calling
`useSearchParams` must sit inside one, or Next.js fails the build. Every page
with filters reads the query string, so every such page has one.

---

## 2. The shell

`components/layout/AppShell.tsx` — one shell for all nine authenticated routes.

```
┌────────────┬──────────────────────────────────────────┐
│            │ header: menu · brand · alerts · account   │
│  sidebar   ├──────────────────────────────────────────┤
│  240px     │ main                                      │
│  (lg+)     │   PageHeader (h1, breadcrumb, actions)    │
│            │   sections…                               │
└────────────┴──────────────────────────────────────────┘
```

- **`lg` and up** — persistent sidebar rail beside the content.
- **below `lg`** — rail hidden; the menu button opens the *same* `SidebarNav`
  in a drawer. One nav list, two presentations: two copies drift, and the
  divergence is only ever noticed on a phone.

The main column is `min-w-0` throughout. This single class is what actually
prevents horizontal page scroll: a flex or grid child defaults to
`min-width: auto`, which lets a wide table or chart expand it past the viewport.

`BackendUnavailable` wraps the page content, so an outage produces one banner
for the whole shell rather than eight identical ones inside eight panels.

---

## 3. Component vocabulary

### Primitives (`components/ui/`)

| Component | Purpose |
| --- | --- |
| `Card`, `Section`, `Stat` | Surfaces. `Section` owns its heading level. |
| `Button`, `IconButton`, `ButtonLink` | `IconButton` *requires* a `label`. |
| `StatusBadge`, `StatusDot` | Status. Always renders a word. |
| `Skeleton`, `LoadingRegion`, `EmptyState`, `ErrorState` | The three non-success states. |
| `Drawer` | Modal panel with focus trap, Escape, and focus restore. |
| `Icon` | The only icon component. Bundled locally; no CDN. |

### Data (`components/data/`, `components/dashboard/`, `components/tables/`)

| Component | Purpose |
| --- | --- |
| `QueryBoundary` | Renders the five Phase 5 query states, once, for everything. |
| `KpiCard`, `StatCard` | A KPI. Displays; never calculates. |
| `OeeBreakdown` | OEE with its three factors, naming the weakest. |
| `TargetVsActual` | Planned / produced / target on one scale. |
| `StatusDistribution` | Segmented bar plus a labelled legend. |
| `AlertRow`, `AlertList` | Alerts, severity first. |
| `DataTable`, `TablePagination` | Server-driven table rendering. |

### Charts (`components/charts/`)

One library: **Recharts 3**. Chosen for declarative React composition, a real
`ResponsiveContainer`, and SVG that stays sharp on high-DPI factory displays.
Spec section 17 forbids a second charting library; `tests/security.test.ts`
asserts there isn't one.

`ChartFrame` wraps every chart and supplies the two things charts usually lack —
see §6.

---

## 4. Design language

Tokens live in `app/globals.css` as CSS custom properties, exposed to Tailwind
through `@theme inline`. Components reference semantic names
(`bg-surface`, `text-muted`, `border-border-base`), never raw palette values, so
dark mode is defined once and cannot be forgotten in a component.

The aesthetic is an operations console, not an admin template: 1px borders, a
6px radius, a flat surface, no shadow stack, no gradients. Every one of those
costs contrast or horizontal space that dense operational data needs.

Two details worth knowing:

- **`font-variant-numeric: tabular-nums` on `body`.** In a column of
  quantities, proportional digits make numbers jitter and the eye cannot scan
  down them.
- **A single global `:focus-visible` rule.** Defined once because a missing
  focus ring is invisible until someone tries the keyboard, by which point it
  is missing from twenty components.

### Status colours

Everything collapses to five tones — `good`, `warn`, `critical`, `neutral`,
`info` — so a machine status, an alert severity, a stock level and a KPI verdict
all read the same way. The mapping functions in `components/ui/Status.tsx` map a
*code* to a tone. They never invent the label: the backend sends `status_label`,
`severity_label` and so on, and that string is what renders.

---

## 5. State handling

Every data region goes through `QueryBoundary`:

| State | Rendered |
| --- | --- |
| `loading` | A skeleton shaped like the content, announced politely |
| `refreshing` | The previous content, unchanged, plus a small header indicator |
| `success` | The content |
| `empty` | A specific sentence — "No production records found for this range" |
| `error` | Title, safe message, and a retry *only* if `canRetry` |

Two of these are the reason the component exists.

**`refreshing` keeps the previous content mounted.** Same DOM, same scroll
position, same focus. The dashboard polls every 30 seconds; treating a refetch
as loading would swap the screen for a skeleton twice a minute, which is exactly
what spec section 16 forbids.

**A retry button appears only when retrying could work.** `canRetry` comes from
Phase 5's `presentError`, which returns false for 401, 403, 404, 422 and 429.
Offering "Try again" on a 403 invites the user to click a button that will fail
identically, forever.

No error message ever contains a status code, a stack, or a URL. Asserted in
`tests/dashboard.test.tsx`.

---

## 6. Charts

Every chart takes a `ChartData` from the Phase 5 adapters. The contract is one
sentence: **adapters map and label; charts draw; neither calculates.**

`ChartFrame` supplies what charts almost always lack:

1. **A text summary**, as a visually hidden `<figcaption>`. WCAG 1.1.1 treats a
   chart as a non-text element needing an equivalent. The summary is built by
   the adapter from the same numbers the chart plots, so it cannot drift.
2. **The data as a real `<table>`**, in a collapsed `<details>`. This is the
   honest fallback: a sentence summarises, but only a table gives the value for
   the 14th. Collapsed, so it costs sighted users nothing.

The SVG itself is `aria-hidden`. Recharts emits hundreds of path and text nodes;
exposing them produces an unusable stream of numbers.

Series after the first are dashed. Differentiating by colour alone fails WCAG
1.4.1 and makes a chart unreadable to a red/green colour-vision deficiency,
which on a factory floor is a certainty rather than a risk.

Animation is off. Redrawing the same series every 30 seconds is the decorative
animation spec section 34 warns against.

---

## 7. Tables

Server-driven throughout, via Phase 5's `useServerTableState` + `useServerTable`.
One page of rows is in the DOM at a time.

Two details that are easy to get wrong and are therefore centralized:

- **A sortable column's `id` is the backend's sort key** — `date`, `produced`,
  `efficiency` — not the field name. `tests/tables.test.tsx` asserts every
  sortable column's id is on the API's allow-list, because a mismatch produces a
  422 the moment a header is clicked.
- **Columns the API cannot sort set `enableSorting: false`**, so no control is
  offered that does not work.

Accessibility: a real `<table>` with `<th scope="col">`, a visually hidden
`<caption>`, `aria-sort` on sortable headers, and — for clickable rows — a real
`<button>` in the first cell. A click handler on the `<tr>` alone is unreachable
without a mouse.

The machine fleet is the deliberate exception: it is unpaginated and unsorted
server-side (a dozen machines, not a dataset), so it renders a plain table
rather than dragging in pagination chrome for twelve rows.

---

## 8. Filters and URL state

Filter state lives in the query string, via `hooks/useUrlFilters.ts`. That buys
reload survival, working Back/Forward, and shareable filtered views.

```
/production?start_date=2026-01-01&end_date=2026-01-31&machine_id=…
```

Rules the hook enforces:

- **Only allow-listed keys are read or written.** An unknown parameter in the
  URL is ignored rather than forwarded to the API, so a crafted link cannot
  inject a query parameter the page never intended to send.
- **Empty means absent.** Clearing a filter removes the key; `?machine_id=` is
  a 422 against a UUID field.
- **Nothing sensitive goes in a URL.** Ids and dates only — URLs end up in
  history, referrers and screenshots.
- **`replace`, not `push`.** Adjusting a date range should not stack twenty
  history entries.

Controls are native `<select>` and `<input>` elements with real `<label>`s. A
native control is keyboard-accessible, screen-reader-correct and touch-friendly
for free; a hand-rolled listbox gets all three subtly wrong. Text search
debounces at 350ms so ten keystrokes are one request.

Filter option lists come from the grouping endpoints
(`/production/by-component`, `/by-shift`, `/by-line`) rather than a reference
API, which does not exist. That turns out better: those endpoints return only
values that can actually match, so a dropdown cannot offer a choice that yields
an empty table.

---

## 9. Responsive behaviour

| Breakpoint | Width | Layout |
| --- | --- | --- |
| base | ~375px | Single column; KPIs stack; drawer nav |
| `sm` | 640px | KPIs two-up; filters begin sharing a row |
| `lg` | 1024px | Sidebar appears; two-column section grids |
| `xl` | 1280px | KPIs four-up; 2:1 chart-and-panel splits |

Rules applied consistently:

- Grids are `grid-cols-1` first, widening upward. No fixed pixel widths.
- Wide content scrolls **inside its card** (`overflow-x-auto`), never the page.
- `min-w-0` on every flex/grid child that can contain a table or chart.
- Touch targets are at least 36px tall (`size="md"` on buttons), above WCAG
  2.2's 24px minimum (2.5.8).

---

## 10. Accessibility

Target: WCAG 2.2 AA.

| Area | How |
| --- | --- |
| Headings | `PageHeader` renders the single `h1`; `Section` renders `h2`/`h3`. Never skipped. |
| Landmarks | `<nav aria-label="Main">`, `<main id="main-content">`, `<search aria-label="Filters">` |
| Skip link | First focusable element in the layout |
| Focus | One global `:focus-visible` ring; `Drawer` traps and restores focus |
| Status | Always a word, never colour alone (1.4.1) |
| Charts | Text summary + data table (1.1.1) |
| Tables | `<th scope>`, `<caption>`, `aria-sort` (1.3.1) |
| Forms | Every control has a `<label>`; placeholders are not labels (3.3.2) |
| Live regions | Loading regions `polite`; errors `alert`; outage `assertive` |
| Motion | Global `prefers-reduced-motion` rule; chart animation off |
| Zoom | `maximumScale: 5`; never blocked |

The KPI card composes its four fragments into one visually hidden sentence.
Read linearly by a screen reader, "Production / 9,250 / 92.5% of target / ↑4.2%"
is a stream of disconnected values; the sentence is as quick to take in aurally
as the card is visually.

---

## 11. Adding a page

1. `app/(app)/<name>/page.tsx` — Server Component, `metadata`, Suspense,
   mount the view.
2. `app/(app)/<name>/<Name>View.tsx` — `"use client"`, hooks, layout.
3. Add the route to `lib/navigation.ts` with its icon and permission.
4. Use existing Phase 5 hooks. Do not fetch directly.
5. Wrap every data region in `QueryBoundary` with a shaped skeleton.
6. If it has filters, use `useUrlFilters` with an explicit key allow-list.
7. If it has a table, use `useServerTableState` + `useServerTable` and column
   definitions from `lib/table/columns.ts`.
8. If you add an icon, run `npm run icons`.

**Do not**: calculate a metric in a component, create an Axios instance, write a
query key inline, use `dangerouslySetInnerHTML`, add a second chart or icon
library, or mark a whole route `"use client"`.
