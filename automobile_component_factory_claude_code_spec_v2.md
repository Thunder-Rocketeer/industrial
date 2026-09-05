# Automobile Component Factory — Claude Code Implementation Specification

## 1. Project Overview

Build a production-quality **Industrial Digital Dashboard for Production, Quality, and Inventory Monitoring** for an **automobile component manufacturing factory**.

The application should simulate a realistic factory environment that manufactures components such as:

- Brake discs
- Drive shafts
- Gears
- Steering components
- Suspension components

The dashboard must combine **production monitoring, quality monitoring, inventory monitoring, machine status, and KPI visualization** into a responsive web application.

This is a course project, but the implementation should follow professional software-engineering practices so that the architecture can be extended later to real machine/IoT data.

---

# 2. Core Technology Stack

## Frontend

- Next.js (App Router)
- TypeScript
- Tailwind CSS
- TanStack Query
- TanStack Table
- TanStack Virtual where useful
- Iconify
- Axios

## Backend

- FastAPI
- Uvicorn
- Gunicorn for production process management
- Supabase / PostgreSQL
- Pydantic
- Redis
- Authlib
- Cryptography

> Interpret the requested "uvcorn" as **Uvicorn** and "guvcorn" as **Gunicorn**.

## Recommended supporting tooling

- ESLint
- Prettier
- Ruff
- Pytest
- HTTPX
- Alembic only if needed for local migration workflows; Supabase migrations should remain the database source of truth
- Docker / Docker Compose for reproducible local development

---

# 3. Primary Goal

Create a dashboard where a factory manager can immediately answer:

1. How much are we producing?
2. Are we meeting today's production target?
3. Which machines are running, idle, or under maintenance?
4. How many components are defective?
5. What are the main defect categories?
6. What is our quality rate?
7. Which materials are running low?
8. What is the current inventory?
9. How is production changing over time?
10. What operational issues require attention?

The UI should prioritize **fast scanning and decision-making**, not excessive decoration.

---

# 4. Application Structure

Use a clear dashboard-oriented information architecture.

## Main routes

```text
/
├── /login
├── /dashboard
├── /production
├── /quality
├── /inventory
├── /machines
├── /analytics
└── /settings
```

Use a shared authenticated application shell:

```text
Sidebar
Top Header
Page Content
Notifications / Toasts
```

The dashboard should work well on:

- Desktop
- Laptop
- Tablet
- Mobile

---

# 5. Dashboard Modules

## 5.1 Executive Dashboard

The primary screen should display:

### KPI cards

- Today's production
- Production target
- Production efficiency
- Defect rate
- First-pass yield
- Machine availability
- Inventory health

Each KPI should show:

- Current value
- Unit
- Short contextual label
- Trend vs previous period
- Accessible status indication

Example:

```text
Production
9,250 / 10,000 units
92.5% achievement
+4.2% vs yesterday
```

---

## 5.2 Production Monitoring

Track production by:

- Date
- Shift
- Machine
- Production line
- Component
- Quantity planned
- Quantity produced
- Quantity accepted
- Quantity rejected

Charts:

- Production by hour
- Production by shift
- Actual vs target
- Production by component
- Production by machine

Filtering:

- Date range
- Shift
- Component
- Machine
- Production line

---

## 5.3 Quality Monitoring

Track:

- Total inspected
- Passed
- Rejected
- Defect rate
- First-pass yield
- Defect type
- Defect severity
- Component

Suggested defects:

```text
Dimensional Out-of-Tolerance
Surface Defect
Crack
Burr
Incorrect Assembly
Thread Damage
Heat Treatment Failure
Material Defect
```

Visualizations:

- Defect rate trend
- Pareto chart of defects
- Rejection by component
- Rejection by machine
- Rejection by shift

---

## 5.4 Inventory Monitoring

Track:

- Raw material
- Component
- Current quantity
- Unit
- Minimum stock
- Reorder point
- Maximum stock
- Supplier
- Last updated

Inventory states:

```text
Healthy
Low
Critical
Overstocked
```

Example raw materials:

```text
Steel billets
Aluminium alloy
Cast iron
Bearing assemblies
Fasteners
Lubricant
Cutting inserts
Packaging material
```

Show:

- Current stock
- Stock utilization
- Low-stock alerts
- Inventory trend
- Materials requiring reorder

---

## 5.5 Machine Monitoring

Each machine should have:

- Machine ID
- Machine name
- Type
- Production line
- Status
- Current component
- Utilization
- Downtime
- Maintenance date

Statuses:

```text
Running
Idle
Maintenance
Offline
```

Possible machines:

```text
CNC Turning Center
CNC Milling Center
Vertical Machining Center
Grinding Machine
Heat Treatment Unit
Inspection Station
Assembly Station
```

---

## 5.6 Analytics

Provide deeper analysis with:

- OEE
- Availability
- Performance
- Quality
- Production efficiency
- Defect trends
- Downtime trends
- Inventory turnover
- Target achievement

### OEE

Use:

```text
OEE = Availability × Performance × Quality
```

Display the three components separately so users can understand why OEE changes.

---

# 6. Data Model

Use Supabase PostgreSQL as the primary persistent database.

Suggested tables:

```text
users
roles
factory_lines
machines
components
production_records
quality_records
defects
inventory_items
inventory_transactions
maintenance_records
daily_targets
shifts
alerts
audit_logs
```

Create appropriate:

- Primary keys
- Foreign keys
- Unique constraints
- NOT NULL constraints
- CHECK constraints
- Indexes
- Created/updated timestamps

Use UUIDs where practical.

Use UTC timestamps in storage.

Convert timestamps for display at the frontend boundary.

---

# 7. Predefined Demo Data

This project must work immediately after setup without requiring manual data entry.

Create realistic predefined data in Supabase.

Seed data should include:

## Factory lines

```text
Line A — Brake Components
Line B — Drivetrain Components
Line C — Steering Components
Line D — Suspension Components
```

## Machines

At least:

- 12 machines
- Different machine types
- Mixed operational states
- Different utilization percentages

## Components

At least:

```text
Brake Disc
Brake Drum
Drive Shaft
CV Joint Housing
Steering Knuckle
Control Arm
Wheel Hub
Gear Blank
Transmission Shaft
Suspension Bracket
```

## Production history

Create at least:

- 30–90 days of historical production
- Multiple shifts
- Multiple machines
- Multiple components
- Realistic variations
- Planned vs actual quantities

Do not generate identical values.

Use a deterministic seed strategy so the same seed produces the same initial database.

## Quality history

Include:

- Passed records
- Rejected records
- Multiple defect categories
- Different defect frequencies
- Machine/component relationships

Make a few defects intentionally more frequent so the Pareto analysis is meaningful.

## Inventory

Include:

- Healthy stock
- Low stock
- Critical stock
- Overstock

Ensure at least a few items trigger alerts.

## Maintenance

Include:

- Completed maintenance
- Upcoming maintenance
- Recently completed maintenance
- A few machines requiring attention

---

# 8. Backend Architecture

Use FastAPI with clear separation of responsibilities.

Recommended structure:

```text
backend/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── api/
│   │   ├── router.py
│   │   └── routes/
│   │       ├── auth.py
│   │       ├── dashboard.py
│   │       ├── production.py
│   │       ├── quality.py
│   │       ├── inventory.py
│   │       ├── machines.py
│   │       └── analytics.py
│   ├── schemas/
│   ├── services/
│   ├── repositories/
│   ├── models/
│   ├── db/
│   ├── cache/
│   ├── security/
│   └── utils/
├── tests/
├── requirements.txt
└── Dockerfile
```

Do not place database logic directly inside route handlers.

Use:

```text
Router -> Service -> Repository -> Database
```

---

# 9. FastAPI API Design

Use versioned APIs.

Base:

```text
/api/v1
```

Endpoints should include:

```text
GET    /api/v1/dashboard/summary
GET    /api/v1/dashboard/trends
GET    /api/v1/production
GET    /api/v1/production/summary
GET    /api/v1/quality
GET    /api/v1/quality/summary
GET    /api/v1/inventory
GET    /api/v1/inventory/alerts
GET    /api/v1/machines
GET    /api/v1/machines/{machine_id}
GET    /api/v1/analytics/oee
GET    /api/v1/analytics/production-efficiency
GET    /api/v1/analytics/defects
```

Support query parameters for filtering and pagination.

Example:

```text
/api/v1/production?start_date=...&end_date=...&machine_id=...&shift=...
```

---

# 10. Pydantic

Use Pydantic models for:

- Request validation
- Response validation
- Configuration
- Query parameter models where helpful

Never return raw unvalidated database structures from public API endpoints.

Define explicit response schemas.

Example concept:

```python
class ProductionSummary(BaseModel):
    total_produced: int
    target: int
    achievement_percentage: float
    rejected: int
    efficiency_percentage: float
```

Use strict validation where appropriate.

---

# 11. Supabase

Use Supabase PostgreSQL as the persistent data layer.

Requirements:

- Store predefined seed data in Supabase.
- Keep credentials in environment variables.
- Never expose the Supabase service-role key to the browser.
- Access privileged Supabase operations only from the backend.
- Apply database constraints.
- Use indexes on frequently filtered columns.
- Prefer aggregation in PostgreSQL rather than transferring huge datasets to the frontend.

Required environment variables should include concepts such as:

```text
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
DATABASE_URL
REDIS_URL
SECRET_KEY
```

Do not hard-code secrets.

---

# 12. Redis Caching

Redis should be used for frequently requested dashboard/analytics data.

Good cache candidates:

- Dashboard summary
- KPI summary
- Production trend
- Quality trend
- Inventory alert counts
- Machine summary
- OEE calculations

Example key pattern:

```text
dashboard:summary:{date}
production:trend:{start}:{end}:{filters_hash}
quality:summary:{start}:{end}:{filters_hash}
inventory:alerts
machines:summary
analytics:oee:{start}:{end}
```

Use sensible TTL values.

Suggested starting points:

```text
Real-time-ish dashboard summary: 15–30 seconds
Charts/trends: 1–5 minutes
Historical analytics: 5–15 minutes
Reference data: 30–60 minutes
```

Make TTL configurable.

---

# 13. Cache Invalidation

Do not blindly cache everything.

When data affecting a cached view changes:

1. Write to database.
2. Invalidate related keys.
3. Recalculate/repopulate cache on next request where appropriate.

Keep cache invalidation centralized in the service/cache layer.

Avoid duplicated cache logic across route handlers.

---

# 14. Frontend Architecture

Recommended structure:

```text
frontend/
├── app/
│   ├── login/
│   ├── dashboard/
│   ├── production/
│   ├── quality/
│   ├── inventory/
│   ├── machines/
│   └── analytics/
├── components/
│   ├── layout/
│   ├── dashboard/
│   ├── production/
│   ├── quality/
│   ├── inventory/
│   ├── machines/
│   ├── charts/
│   ├── tables/
│   └── ui/
├── lib/
│   ├── api/
│   ├── query/
│   ├── utils/
│   └── constants/
├── hooks/
├── types/
└── providers/
```

---

# 15. Axios

Create one centralized Axios client.

Do not create arbitrary Axios instances in components.

The client should handle:

- API base URL
- Authentication credentials/token strategy
- Request headers
- Response handling
- Error normalization
- Timeouts

Use typed API functions.

Example:

```text
api/dashboard.ts
api/production.ts
api/quality.ts
api/inventory.ts
api/machines.ts
api/analytics.ts
```

---

# 16. TanStack Query

Use TanStack Query for all server state.

Requirements:

- Query keys must be structured and consistent.
- Configure stale times based on data volatility.
- Avoid unnecessary refetches.
- Use retry policies carefully.
- Show proper loading/error states.
- Prefetch likely next views.
- Invalidate affected queries after mutations.

Do not use React local state as a replacement for server-state management.

Suggested starting settings:

```text
Dashboard:
staleTime = 30 seconds

Historical charts:
staleTime = 2–5 minutes

Reference data:
staleTime = 30 minutes or more
```

Tune these values based on actual usage.

---

# 17. TanStack Table

Use TanStack Table for:

- Production records
- Quality records
- Inventory
- Machines
- Maintenance
- Alerts

Required features:

- Sorting
- Filtering
- Pagination
- Column visibility
- Responsive handling
- Empty states

For very large tables, use virtualization.

---

# 18. Responsive Design

Design mobile-first with Tailwind CSS.

Desktop:

```text
Sidebar + multi-column dashboard
```

Tablet:

```text
Collapsible sidebar
2-column layouts
```

Mobile:

```text
Stacked KPI cards
Horizontally scrollable data tables where unavoidable
Compact charts
Bottom/slide-out navigation if appropriate
```

Never allow essential information to disappear only because the viewport is narrow.

Avoid fixed-width components that cause horizontal page scrolling.

Use responsive Tailwind breakpoints.

---

# 19. Accessibility — WCAG

Target **WCAG 2.2 AA** as the accessibility baseline.

Requirements:

- Semantic HTML
- Correct heading hierarchy
- Keyboard navigability
- Visible focus states
- Accessible buttons
- Accessible form labels
- Accessible table headers
- ARIA only where necessary
- Screen-reader-friendly status messages
- Do not rely on color alone
- Sufficient contrast
- Respect reduced-motion preferences
- Minimum practical touch target sizes
- Charts must provide textual/contextual alternatives

Example:

Do not display only:

```text
🔴
```

Instead use:

```text
Critical — inventory below reorder level
```

Charts should have accessible summaries/data tables where practical.

---

# 20. Visual Design

Use a modern industrial SaaS dashboard aesthetic.

Desired qualities:

- Clean
- Professional
- High information density
- Strong hierarchy
- Minimal visual noise
- Consistent spacing
- Consistent typography
- Subtle borders
- Clear status states

Avoid:

- Excessive gradients
- Overly rounded cards
- Huge decorative graphics
- Unnecessary animations
- Dashboard clutter

Use Iconify consistently for icons.

Do not mix multiple icon libraries.

---

# 21. Loading and Error States

Every async screen must have:

- Loading state
- Error state
- Empty state
- Success state where appropriate

Use skeleton loading rather than replacing the entire UI with a spinner.

Example:

```text
Loading:
[ KPI Skeleton ] [ KPI Skeleton ] [ KPI Skeleton ]

Error:
Unable to load production data.
[Try again]
```

Errors should be human-readable.

Do not expose stack traces or internal server details to users.

---

# 22. Fast Development / Reloading

Developer experience is important.

## Frontend

Use Next.js development server with fast refresh.

Avoid unnecessarily expensive imports.

Use dynamic imports for heavy components when justified.

## Backend

Run FastAPI with Uvicorn reload during development:

```bash
uvicorn app.main:app --reload
```

Do not use reload in production.

## Production

Use Gunicorn with Uvicorn workers:

```bash
gunicorn app.main:app -k uvicorn.workers.UvicornWorker
```

Number of workers should be configurable based on deployment resources.

---

# 23. Performance Requirements

Optimize for fast first render and responsive interaction.

Frontend:

- Server Components by default where appropriate
- Client Components only when interactivity requires them
- Lazy-load heavy charts
- Minimize unnecessary rerenders
- Memoize expensive calculations only where measured/justified
- Avoid fetching duplicate data
- Use TanStack Query caching
- Use pagination/virtualization for large datasets

Backend:

- Async endpoints where appropriate
- Avoid blocking operations in async request paths
- Database indexes
- Aggregation queries
- Redis caching
- Pagination
- Avoid N+1 queries
- Return only required fields

---

# 24. API Response Design

Use a consistent response structure where appropriate.

For list endpoints:

```json
{
  "data": [],
  "pagination": {
    "page": 1,
    "page_size": 25,
    "total": 1250
  }
}
```

For dashboard aggregates:

```json
{
  "data": {
    "production": {},
    "quality": {},
    "inventory": {},
    "machines": {}
  }
}
```

Do not over-wrap every tiny response unnecessarily.

Keep responses predictable and typed.

---

# 25. Authentication

Use Authlib for OAuth/OIDC integration. Authentication MUST follow the Google OAuth 2.0 / OpenID Connect architecture defined in Sections 54–72.

Implement secure OAuth authentication suitable for a course deployment, with backend-issued JWT access tokens and server-side RBAC.

Requirements:

- Login page
- Protected dashboard routes
- Secure session/token handling
- Authorization checks
- Role-aware access structure

Suggested roles:

```text
Admin
Factory Manager
Production Supervisor
Quality Engineer
Inventory Manager
Viewer
```

Do not store plaintext passwords.

Do not place sensitive tokens in localStorage unless there is a compelling, documented reason.

Prefer secure HTTP-only cookie-based authentication for a traditional web application.

---

# 26. Cryptography

Use the `cryptography` package only for appropriate security-sensitive operations.

Do not invent custom cryptographic algorithms.

Use established primitives/libraries for:

- Secure secret handling
- Encryption where required
- Signing/verification where appropriate

Password hashing should use a dedicated password-hashing strategy rather than raw encryption.

---

# 27. Security Requirements

Implement:

- Environment-based secrets
- CORS configured explicitly
- Input validation
- Authentication on protected endpoints
- Authorization checks
- Rate limiting where appropriate
- Secure cookies
- Security headers where appropriate
- No sensitive values in logs
- No service-role credentials in frontend code
- Parameterized/ORM/database-safe queries
- Proper exception handling

Do not commit:

```text
.env
.env.local
credentials
private keys
service-role keys
```

Provide `.env.example`.

---

# 28. Logging and Observability

Use structured server-side logging.

Log:

- Request method/path
- Response status
- Duration
- Important operational events
- Authentication failures

Do not log:

- Passwords
- Access tokens
- Secret keys
- Session contents
- Sensitive credentials

Add request IDs/correlation IDs where practical.

---

# 29. Database Indexing

Prioritize indexes for:

```text
production_records(timestamp)
production_records(machine_id)
production_records(component_id)
production_records(shift_id)

quality_records(timestamp)
quality_records(machine_id)
quality_records(component_id)
quality_records(defect_id)

inventory_items(status)
inventory_items(component_id)

machines(status)
maintenance_records(machine_id)
```

Do not blindly index every column.

Use indexes based on real query patterns.

---

# 30. Seed Strategy

Provide a repeatable seed mechanism.

Example:

```bash
python -m app.db.seed
```

The seed should:

1. Create/verify reference data.
2. Insert deterministic demo data.
3. Preserve referential integrity.
4. Avoid accidental duplicate records.
5. Be safe to run in a fresh development database.

Provide a documented reset strategy for developers.

---

# 31. Demo Data Behavior

The dashboard should feel alive.

Use realistic trends such as:

- Morning shift beginning slowly
- Midday production increasing
- Occasional downtime
- Some machines consistently more efficient
- A small defect spike on one component
- Inventory gradually declining
- Periodic replenishment

Do not make values random on every API request.

The database is the source of truth.

Optional future enhancement:

A background simulation worker can update a small amount of data periodically, but **do not implement this unless it improves the course demonstration**. The base application must work entirely from predefined Supabase data.

---

# 32. Charts

Use a consistent charting solution compatible with Next.js.

Charts must show:

- Units
- Time ranges
- Tooltips
- Legends where useful
- Accessible text summaries

Required charts:

1. Production trend
2. Target vs actual
3. Defect trend
4. Defect Pareto
5. Machine utilization
6. Inventory levels
7. OEE trend

Avoid rendering dozens of charts simultaneously.

---

# 33. Dashboard Refresh

Provide sensible automatic refresh.

The dashboard may refetch summary data approximately every:

```text
30 seconds
```

Do not aggressively poll every endpoint.

Historical analytics should generally not poll.

Pause/reduce unnecessary polling when the browser tab is hidden where practical.

---

# 34. Notifications / Alerts

Provide an alerts panel containing:

```text
Critical inventory
Machine maintenance due
Production target risk
High defect rate
Machine offline
```

Severity:

```text
Info
Warning
Critical
```

Alerts should include:

- Title
- Description
- Timestamp
- Severity
- Related machine/component where applicable

---

# 35. Frontend Folder Conventions

Use consistent naming.

Example:

```text
components/dashboard/KpiCard.tsx
components/dashboard/ProductionTrendChart.tsx
components/inventory/InventoryTable.tsx
components/machines/MachineStatusTable.tsx

lib/api/dashboard.ts
lib/api/production.ts

hooks/useProduction.ts
hooks/useInventory.ts

types/production.ts
types/inventory.ts
```

Avoid giant components.

Break pages into focused components.

---

# 36. Type Safety

Avoid `any`.

Use:

- TypeScript interfaces/types
- Pydantic schemas
- Explicit API response types

Frontend API types should closely mirror backend contracts.

Where practical, structure the project so API contract drift is easy to detect.

---

# 37. Error Handling

Backend:

- Use FastAPI exception handlers
- Return stable error codes/messages
- Keep internal details out of public responses

Frontend:

- Normalize Axios errors
- Show actionable error messages
- Provide retry actions
- Preserve already loaded data where possible during transient failures

Example:

```text
Production data could not be refreshed.
Showing the most recently loaded data.
[Retry]
```

---

# 38. Production Deployment

Design the application so the deployment architecture can be:

```text
Browser
   |
   v
Next.js
   |
   v
FastAPI / Gunicorn
   |
   +----> Redis
   |
   +----> Supabase PostgreSQL
```

For local development:

```text
Browser
   |
Next.js dev server
   |
FastAPI + Uvicorn reload
   |
Redis
   |
Supabase
```

Use Docker Compose if practical.

---

# 39. Environment Configuration

Create:

```text
frontend/.env.example
backend/.env.example
```

Frontend variables should contain only values safe for browser exposure.

Backend variables may contain secrets.

Clearly distinguish:

```text
NEXT_PUBLIC_*
```

from server-only secrets.

---

# 40. API Documentation

FastAPI's OpenAPI docs should remain enabled in development.

Provide clear endpoint summaries and response models.

The API should be understandable without reading implementation code.

---

# 41. Testing

## Backend

Use Pytest for:

- Authentication
- Validation
- Production calculations
- Quality calculations
- Inventory status calculations
- OEE calculation
- API responses
- Cache behavior where practical

## Frontend

Test critical:

- Dashboard rendering
- Loading states
- Error states
- Filters
- Tables
- Navigation
- Authenticated route behavior

Focus testing effort on business-critical functionality.

---

# 42. Business Logic

Do not hard-code KPI formulas inside UI components.

Keep calculations in backend services where the calculation depends on stored operational data.

Examples:

```text
Production achievement
Defect rate
First-pass yield
Availability
Performance
Quality
OEE
Inventory health
```

Frontend should primarily visualize API results.

---

# 43. KPI Definitions

Use these definitions consistently.

## Production Achievement

```text
Actual Production / Planned Production × 100
```

## Defect Rate

```text
Rejected Units / Inspected Units × 100
```

## First Pass Yield

```text
Units passing inspection without rework / Total units × 100
```

## Availability

```text
Operating Time / Planned Production Time × 100
```

## Performance

Use actual output relative to ideal output for operating time.

## Quality

```text
Good Units / Total Units × 100
```

## OEE

```text
Availability × Performance × Quality
```

Document assumptions used in demo calculations.

---

# 44. UX Rules

The user should understand the main state of the factory within approximately 5–10 seconds.

The dashboard hierarchy should be:

```text
1. Critical alerts
2. Overall KPIs
3. Production status
4. Quality status
5. Machine status
6. Inventory
7. Deeper analytics
```

Avoid forcing users to navigate through multiple screens for basic factory status.

---

# 45. Accessibility-Friendly Status System

Never communicate state through color alone.

Instead of:

```text
Green
Yellow
Red
```

Display:

```text
Healthy
Warning
Critical
```

Optionally use icons in addition to text.

Ensure text remains understandable in grayscale.

---

# 46. Performance Budget Mindset

Aim for:

- Fast navigation
- Minimal blocking JavaScript
- Efficient API payloads
- No unnecessary polling
- No huge tables rendered at once
- No expensive recalculations in render paths

Measure before adding complicated optimization.

---

# 47. Code Quality

Follow:

- Single responsibility
- DRY where appropriate
- Explicit interfaces
- Small functions
- Clear naming
- No dead code
- No duplicated API logic
- No magic numbers for important business rules
- Environment-configurable settings

Do not over-engineer a course project.

Use production-quality practices without building unnecessary enterprise abstractions.

---

# 48. Required Developer Experience

Provide README documentation containing:

```text
Project overview
Architecture
Prerequisites
Environment variables
Supabase setup
Redis setup
Database seed
Frontend setup
Backend setup
Development commands
Testing
Production build
Deployment notes
```

Recommended commands:

```bash
# frontend
npm install
npm run dev
npm run lint
npm run build

# backend
uvicorn app.main:app --reload
pytest

# production backend
gunicorn app.main:app -k uvicorn.workers.UvicornWorker
```

---

# 49. Claude Code Implementation Sequence

Implement in the following order.

## Phase 1 — Repository setup

Create:

```text
frontend/
backend/
docs/
docker-compose.yml
README.md
.env.example files
```

Configure TypeScript, Tailwind, linting, formatting, and Python tooling.

## Phase 2 — Database

Design Supabase schema.

Create:

- Tables
- Relationships
- Constraints
- Indexes

Then create deterministic seed data.

## Phase 3 — Backend

Implement:

- Configuration
- Database connection
- Pydantic schemas
- Repositories
- Services
- Cache layer
- Auth
- API routes
- Error handling
- Logging

## Phase 4 — Frontend foundation

Implement:

- App shell
- Sidebar
- Header
- Authentication
- Theme/styling foundations
- Axios client
- TanStack Query provider

## Phase 5 — Dashboard

Implement:

- KPI cards
- Alerts
- Production trend
- Quality summary
- Machine status
- Inventory health

## Phase 6 — Detailed modules

Implement:

- Production
- Quality
- Inventory
- Machines
- Analytics

with tables, filters and charts.

## Phase 7 — Accessibility and responsive polish

Test:

- Keyboard navigation
- Screen-reader semantics
- Contrast
- Mobile layouts
- Tablet layouts
- Focus states

## Phase 8 — Performance

Review:

- API calls
- Query caching
- Redis caching
- Database queries
- Bundle size
- Chart rendering
- Table rendering

## Phase 9 — Testing

Add and run backend/frontend tests.

## Phase 10 — Final documentation

Document:

- Architecture
- Setup
- Seed process
- Demo credentials
- API
- Deployment
- Known assumptions

---

# 50. Demo Credentials

Create a clearly documented demo authentication setup using seeded development-only accounts.

Example:

```text
admin@factory.local
manager@factory.local
quality@factory.local
inventory@factory.local
```

Do not reuse these credentials in production.

Store development passwords securely and document them only for the local/demo environment.

---

# 51. Final Acceptance Criteria

The implementation is complete only when:

### Functionality

- Dashboard loads real seeded Supabase data.
- Production module works.
- Quality module works.
- Inventory module works.
- Machine module works.
- Analytics module works.
- Filters work.
- Tables work.
- Charts work.
- Alerts work.
- Authentication protects private routes.

### Data

- Supabase contains realistic predefined factory data.
- Historical production data exists.
- Quality data exists.
- Inventory data exists.
- Machine data exists.
- Maintenance data exists.

### Performance

- TanStack Query caching is configured.
- Redis caching is implemented for expensive/frequently requested data.
- Database queries are indexed appropriately.
- No obvious N+1 query patterns.
- Large tables are paginated/virtualized as needed.

### Accessibility

- WCAG 2.2 AA is the target.
- Keyboard navigation works.
- Focus states are visible.
- Important state is not conveyed through color alone.
- Labels and headings are semantic.
- Charts have accessible descriptions or supporting data.

### Development

- Frontend fast refresh works.
- Backend Uvicorn reload works.
- Production Gunicorn command works.
- Environment variables are documented.
- README setup instructions work from a clean checkout.

---

# 52. Important Implementation Principles

1. **Supabase is the persistent source of truth.**
2. **Redis is a cache, not the primary database.**
3. **TanStack Query manages frontend server state.**
4. **Axios is centralized.**
5. **FastAPI route handlers stay thin.**
6. **Business logic belongs in backend services.**
7. **Pydantic validates API contracts.**
8. **Never expose server secrets to the browser.**
9. **Use deterministic seeded demo data.**
10. **Optimize after measuring, not by adding unnecessary complexity.**
11. **Build responsive and accessible UI from the beginning.**
12. **Prefer clear, maintainable code over clever code.**

---

# 53. Definition of Done

The final application should look and behave like a small but credible **Industry 4.0 manufacturing operations dashboard**.

A lecturer should be able to open the application, log in, and immediately see:

```text
FACTORY HEALTH
        |
        +-- Production
        +-- Quality
        +-- Machines
        +-- Inventory
        +-- Alerts
        +-- Analytics
```

All displayed information must come from the seeded Supabase database through the FastAPI backend, with appropriate frontend caching and Redis caching.

The implementation should be polished enough for a course demonstration while remaining structured enough to extend later with live IoT/machine data.

---

# 54. Mandatory Security Architecture

Security is a first-class requirement. The implementation must use a defense-in-depth approach and must not treat authentication alone as sufficient security.

The authentication architecture must follow **OAuth 2.0 / OpenID Connect using Google as the identity provider**, with the FastAPI backend issuing and validating short-lived **JWT access tokens** for API authorization.

Do not implement a custom password-login system for Google-authenticated users.

## 54.1 Authentication Flow — Google OAuth 2.0 / OIDC

Implement the Authorization Code flow with Google as the OAuth/OIDC provider.

High-level flow:

```text
Browser
   |
   | 1. Login with Google
   v
Next.js
   |
   | 2. Redirect to backend OAuth endpoint
   v
FastAPI
   |
   | 3. Authorization request
   v
Google OAuth / OIDC
   |
   | 4. Authorization code
   v
FastAPI callback
   |
   | 5. Exchange code for tokens
   | 6. Validate issuer, audience, nonce, state
   | 7. Obtain verified Google identity
   v
FastAPI
   |
   | 8. Create/update local user
   | 9. Issue application JWT access token
   v
Secure session / HTTP-only cookie
   |
   v
Next.js -> FastAPI protected APIs
```

Use Authlib for OAuth/OIDC integration.

Required OAuth security controls:

- Authorization Code flow
- PKCE where supported/applicable
- `state` validation
- OIDC `nonce` validation
- Strict redirect URI allow-list
- Exact issuer validation for Google
- Audience/client-ID validation
- Signature validation of OIDC ID tokens
- Validate token expiry (`exp`)
- Validate issued-at (`iat`) where applicable
- Do not accept arbitrary OAuth providers through a user-controlled URL
- Never trust an email address before the Google identity/token has been cryptographically verified

Do not implement OAuth by manually constructing or decoding tokens without proper validation.

## 54.2 Google Provider Configuration

Use environment variables for Google OAuth configuration:

```text
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI
GOOGLE_OIDC_ISSUER
```

The production redirect URI must be explicitly configured and must not be derived from an arbitrary incoming `Host` or query parameter.

Use HTTPS in production.

For this course/demo project, development redirect URIs may use localhost, but production configuration must reject insecure arbitrary origins.

---

# 55. JWT Security

Use JWTs for application API authorization.

## 55.1 JWT Requirements

JWTs must:

- Have a short expiration time.
- Include `sub` as the application user identifier.
- Include an issuer (`iss`).
- Include an audience (`aud`).
- Include issued-at (`iat`).
- Include expiration (`exp`).
- Use a unique token ID (`jti`) where revocation/replay controls require it.
- Use a strong signing key stored only in backend secrets.
- Reject expired tokens.
- Reject tokens with an unexpected issuer.
- Reject tokens with an unexpected audience.
- Reject unsupported/invalid signing algorithms.

Never accept `alg=none`.

Do not dynamically select the verification algorithm from the incoming token header.

## 55.2 Signing Strategy

Prefer an asymmetric JWT signing algorithm such as RS256/ES256 for production deployments where practical, with the verification key kept separate from the signing secret.

The implementation must make the algorithm explicit and configurable, with a secure production default.

Do not use weak or hard-coded secrets.

## 55.3 Token Lifetime

Suggested starting configuration:

```text
Access token: 10–15 minutes
Refresh/session mechanism: longer-lived, rotated securely
```

Do not create unnecessarily long-lived access tokens.

If refresh tokens are implemented:

- Rotate refresh tokens.
- Store refresh tokens securely.
- Detect refresh-token reuse where practical.
- Revoke the token family after detected reuse.

For the browser application, prefer a secure HTTP-only session/refresh cookie rather than exposing long-lived refresh tokens to JavaScript.

## 55.4 JWT Storage

Do **not** store long-lived JWTs or refresh tokens in `localStorage`.

Preferred browser model:

```text
HTTP-only
Secure
SameSite=Lax or Strict where compatible
```

Keep the access-token handling as isolated as possible from application JavaScript.

Never expose JWT signing keys to the frontend.

---

# 56. Authorization and RBAC

Authentication answers **who the user is**. Authorization must separately determine **what the user is allowed to do**.

Use role-based access control.

Roles:

```text
Admin
Factory Manager
Production Supervisor
Quality Engineer
Inventory Manager
Viewer
```

Define a central authorization policy rather than scattering role checks throughout route handlers.

Example policy concepts:

```text
Viewer:
  Read dashboard and analytics

Production Supervisor:
  Viewer + production operations

Quality Engineer:
  Viewer + quality operations

Inventory Manager:
  Viewer + inventory operations

Factory Manager:
  Read all operational data + management functions

Admin:
  Full application administration
```

Every protected endpoint must verify authorization on the backend.

Never rely only on hiding frontend buttons.

A user who manually calls an API must receive `403 Forbidden` when authenticated but unauthorized.

---

# 57. SQL Injection Prevention

The application must explicitly defend against SQL injection.

Rules:

- Never construct SQL using string concatenation with user-provided values.
- Never interpolate request query parameters directly into SQL strings.
- Use parameterized queries / safe query builders / ORM mechanisms.
- Validate and constrain sort fields and sort directions against allow-lists.
- Validate filter fields against known schema fields.
- Never allow an arbitrary SQL fragment to be supplied through an API parameter.
- Use Pydantic validation before data reaches the repository layer.

Example unsafe pattern — **do not use**:

```python
query = f"SELECT * FROM production_records WHERE machine_id = '{machine_id}'"
```

Use parameterized database operations instead.

For dynamic sorting, use an explicit mapping:

```text
"production" -> production_quantity
"date"       -> timestamp
"machine"    -> machine_id
```

Reject unknown sort fields.

Test the API with malicious SQL-like inputs such as:

```text
' OR '1'='1
'; DROP TABLE production_records; --
```

The expected behavior is validation/rejection or safe literal handling, never SQL execution.

---

# 58. XSS Protection

The application must protect against reflected, stored, and DOM-based cross-site scripting.

## Backend

- Validate and sanitize user-controlled values where they can become rich content.
- Never return unsafely rendered HTML generated from arbitrary user input.
- Use proper output encoding by default.
- Avoid accepting raw HTML unless there is a documented business requirement.
- When HTML is genuinely required, sanitize it with a well-maintained allow-list sanitizer.

## Frontend

- React/Next.js escaping is the default mechanism.
- Do not use `dangerouslySetInnerHTML` for untrusted content.
- If `dangerouslySetInnerHTML` is absolutely necessary, sanitize the content before rendering and document why it is required.
- Never directly inject user-controlled strings into the DOM.
- Do not construct JavaScript from strings.
- Avoid unsafe URL schemes such as `javascript:` in user-controlled links.

Test inputs such as:

```html
<script>alert('XSS')</script>
<img src=x onerror=alert('XSS')>
```

They must render as inert text or be rejected/sanitized.

## Content Security Policy

Add a strong Content Security Policy where compatible with the Next.js application and OAuth requirements.

Start from a restrictive policy and explicitly allow only required script, style, image, font, API, and frame/connect sources.

Do not use broad policies such as:

```text
script-src * 'unsafe-inline' 'unsafe-eval'
```

unless there is a documented technical necessity, and do not weaken CSP merely to make an avoidable implementation work.

Use nonces/hashes or Next.js-compatible CSP patterns where necessary.

---

# 59. CSRF Protection

Because the browser application uses cookies for secure authentication/session handling, implement CSRF protections for state-changing requests.

Use a combination of:

- `SameSite` cookies
- CSRF token/double-submit strategy where required
- Strict `Origin` / `Referer` validation for state-changing requests where appropriate
- Explicit allowed frontend origins

Require CSRF protection on:

```text
POST
PUT
PATCH
DELETE
```

OAuth callback endpoints must also validate the OAuth `state` parameter.

Do not assume CORS is a CSRF protection mechanism.

---

# 60. Rate Limiting

Implement Redis-backed API rate limiting.

Rate limits must be applied at minimum to:

- OAuth initiation
- OAuth callback
- Authentication/session endpoints
- Sensitive API endpoints
- Expensive analytics endpoints
- Export/report endpoints if implemented

Use a combination of IP-, user-, and route-based limits where appropriate.

Example starting policies:

```text
OAuth initiation:
    10 requests / minute / IP

OAuth callback:
    10 requests / minute / IP

General authenticated API:
    120 requests / minute / user

Expensive analytics:
    30 requests / minute / user

Unauthenticated general API:
    60 requests / minute / IP
```

These are starting values, not immutable requirements. Make limits configurable through environment/configuration.

Use Redis so limits work consistently across multiple backend workers/instances.

Return:

```text
429 Too Many Requests
```

with an appropriate `Retry-After` header where practical.

Do not rate-limit only at the frontend. Backend enforcement is mandatory.

Avoid trusting arbitrary `X-Forwarded-For` headers unless the application is deployed behind a configured, trusted reverse proxy.

---

# 61. CORS Policy

Configure CORS explicitly.

Do not use:

```python
allow_origins=["*"]
```

for authenticated browser requests.

Use explicit allowed origins, for example:

```text
http://localhost:3000
https://app.example.com
```

The actual production domain must come from configuration.

Do not reflect arbitrary incoming `Origin` headers.

When credentials/cookies are used, configure CORS appropriately and never combine credentialed requests with wildcard origins.

---

# 62. Security Headers

Add appropriate HTTP security headers at the web/application boundary.

At minimum evaluate and implement:

```text
Content-Security-Policy
Strict-Transport-Security (production HTTPS)
X-Content-Type-Options: nosniff
Referrer-Policy
Permissions-Policy
```

Use framing protection (`frame-ancestors` through CSP) rather than relying solely on legacy headers.

Do not add headers with arbitrary values just for appearance; configure them according to actual application behavior.

---

# 63. Input Validation

Every externally supplied input must be validated.

Validate:

- Query parameters
- Path parameters
- JSON request bodies
- Pagination values
- Date ranges
- Enum values
- UUIDs
- Sorting fields
- Search strings
- Numeric limits

Examples:

```text
page >= 1
page_size within a bounded range such as 1–100
end_date >= start_date
IDs must be valid UUIDs
status must belong to known enum values
```

Reject excessively large request payloads where practical.

Do not rely on frontend validation for security.

---

# 64. Pagination and Resource Exhaustion

Prevent abuse of expensive endpoints.

Do not permit requests such as:

```text
?page_size=100000000
```

Set bounded maximum page sizes.

Expensive date-range analytics should have reasonable limits or require aggregation.

Do not return the entire production history in one request.

Use pagination and server-side aggregation.

---

# 65. Secrets Management

Never commit secrets to Git.

Forbidden in source code:

```text
Google client secret
Supabase service-role key
JWT private key
Redis credentials
Encryption keys
Database passwords
```

Use environment variables or a deployment secret manager.

Provide safe placeholders in `.env.example`.

Ensure:

```text
.env
.env.local
*.pem
*.key
```

and other secret material are included in `.gitignore` as appropriate.

Do not print secrets in logs or exception messages.

---

# 66. Supabase Security

The browser must never receive the Supabase service-role key.

The application architecture must maintain clear separation:

```text
Browser
   |
   v
Next.js
   |
   v
FastAPI
   |
   +---- Supabase/PostgreSQL
```

Privileged database operations must stay server-side.

Where Supabase client access is exposed directly to the frontend in any future enhancement, configure Row Level Security (RLS) correctly and never assume the frontend is trusted.

For the current architecture, prefer backend-mediated data access so authorization and business rules remain centralized.

---

# 67. Audit Logging

Create an audit log for security-sensitive actions.

Examples:

```text
Login success
Login failure
OAuth callback failure
Role/permission change
Inventory modification
Production record modification
Quality record modification
Maintenance update
Administrative action
```

Audit records should contain, where appropriate:

```text
Actor/user ID
Action
Resource type
Resource ID
Timestamp
Success/failure
Request/correlation ID
Relevant metadata (without secrets)
```

Never store raw access tokens, refresh tokens, OAuth client secrets, or passwords in audit logs.

---

# 68. Error Handling and Information Disclosure

Do not expose:

- Stack traces
- SQL statements
- Database connection strings
- Internal filesystem paths
- JWT signing details
- OAuth client secrets
- Redis connection details

Production API errors should be safe and actionable.

Example:

```json
{
  "error": {
    "code": "PRODUCTION_QUERY_FAILED",
    "message": "Unable to retrieve production data."
  }
}
```

Detailed technical errors should be available only in protected server logs.

---

# 69. Dependency and Supply-Chain Security

Keep dependencies current and pinned/lockfile-managed.

Use:

```text
npm lockfile
Python dependency pinning/constraints
```

Run dependency vulnerability checks periodically.

Do not add a package merely because it is convenient when native framework functionality is sufficient.

Review packages that handle:

- Authentication
- Cryptography
- HTML sanitization
- JWTs
- Database connectivity

Prefer established, maintained libraries.

---

# 70. Security Testing Requirements

Add security-focused tests in addition to normal unit/integration tests.

Test at minimum:

## Authentication

- Invalid OAuth state rejected
- Invalid OAuth nonce rejected
- Invalid issuer rejected
- Invalid audience rejected
- Expired tokens rejected
- Invalid signature rejected
- Unsupported JWT algorithm rejected

## Authorization

- Unauthenticated API requests return `401`
- Authenticated but unauthorized requests return `403`
- Viewer cannot perform manager/admin operations

## SQL Injection

- Malicious filter values cannot alter query semantics
- Malicious sort values are rejected
- No raw SQL interpolation from user input

## XSS

- Script payloads are not executed
- Stored malicious strings remain inert
- Unsafe HTML is sanitized/rejected

## Rate Limiting

- Exceeding limits returns `429`
- Redis-backed limits work consistently across workers
- `Retry-After` is returned where applicable

## CSRF

- Invalid/missing CSRF protection blocks unsafe state-changing requests where applicable
- OAuth `state` is mandatory and validated

## Security Headers

Automated tests should verify the expected important security headers are present in production configuration.

---

# 71. Security Configuration Checklist

Before considering the application complete, verify:

```text
[ ] Google OAuth 2.0 / OIDC is configured
[ ] Authorization Code flow is used
[ ] OAuth state validation is implemented
[ ] OIDC nonce validation is implemented
[ ] OAuth redirect URIs are allow-listed
[ ] Google issuer/audience/signature/expiry are validated
[ ] JWT access tokens are short-lived
[ ] JWT issuer/audience/expiry/signature are validated
[ ] `alg=none` and algorithm confusion are rejected
[ ] JWT signing keys are backend-only
[ ] Refresh/session cookies are Secure + HttpOnly
[ ] SameSite policy is configured
[ ] RBAC is enforced by the backend
[ ] SQL queries are parameterized
[ ] Dynamic filters/sorts use allow-lists
[ ] XSS protections are enabled
[ ] `dangerouslySetInnerHTML` is avoided for untrusted content
[ ] CSP is implemented appropriately
[ ] CSRF protection is implemented for cookie-authenticated state changes
[ ] CORS uses an explicit origin allow-list
[ ] Redis-backed rate limiting is enabled
[ ] Request size/pagination limits are enforced
[ ] Security headers are configured
[ ] Secrets are environment/deployment-managed
[ ] Supabase service-role key never reaches the browser
[ ] Audit logging exists for security-sensitive events
[ ] Production errors do not disclose internal details
[ ] Security tests cover auth, authz, injection, XSS, CSRF, and rate limiting
```

---

# 72. Revised Security-First Definition of Done

The final implementation is not complete merely because the dashboard works.

It must also satisfy the following security conditions:

- Google OAuth 2.0 / OpenID Connect authentication is functional.
- Application API authorization uses securely validated JWTs.
- Authentication and authorization are enforced server-side.
- SQL injection defenses are implemented and tested.
- XSS defenses are implemented and tested.
- CSRF protections are implemented for cookie-authenticated state-changing requests.
- Redis-backed rate limiting protects authentication and API endpoints.
- CORS is explicitly allow-listed.
- Important security headers are configured.
- Secrets are never committed or exposed to the client.
- Supabase privileged credentials remain backend-only.
- Audit logs capture important security and administrative actions without sensitive secrets.
- Security-related failures produce safe errors and useful server-side logs.
- Automated tests demonstrate that the above controls actually work.

Security should be implemented as part of the initial architecture, not retrofitted after the UI is complete.
