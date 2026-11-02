# Build progress

## Layer 1 — Application foundation

### Completed

- Preserved the landing page at `/`; added the React/TypeScript application at `/app` and FastAPI API at `/api/v1`.
- Added request IDs, structured errors, health/readiness endpoints, error boundaries, MongoDB organization/user foundations, and an explicit migration runner.
- Configured Redis, Celery, S3-compatible storage, and environment-driven service connections.

### Verification

- Earlier validation: landing tests, frontend build, backend tests, request/error checks, and migration-runner idempotence passed.
- Real database startup and transaction behavior were not verified against a live MongoDB deployment.

### Known limitations

- Local and production database, Redis, SMTP and object storage services must be supplied separately.

## Layer 2 — Authentication and organization isolation

### Completed

- Added verified registration, transactional organization and owner membership creation, login/logout, expiring single-use verification/reset tokens, generic recovery responses, sessions, CSRF, and Redis rate limits.
- Added role-aware organization isolation, SMTP delivery configuration, and account/workspace screens.
- Preserved public sample data as browser-local; it is not copied into user accounts.

### Verification

- Earlier validation covered account journeys, cross-organization guessed IDs, role restrictions, expiry/reuse, revocation, protected routes, and rate limits.
- Current backend suite: 35 passed, including authentication and isolation coverage.

### Known limitations

- Live SMTP delivery, live MongoDB transaction behavior, and full deployment with provider credentials have not been verified.

## Layer 3 — Factory onboarding and asset registry

### Completed

- Added MongoDB migration `0003_factory_assets`, organization-scoped factory/line/machine/component/sensor CRUD, audit history, templates, operating states, and archive/reopen flows.
- Added factory timezone, unit preferences, and weekly/overnight shifts.
- Templates remain descriptive; selecting equipment does not create a validated physics model.

### Verification

- Earlier validation covered registry CRUD, isolation, parent-child lifecycle rules, validation, audit, and concurrent lifecycle changes.
- Persistent data and real transaction behavior have not been verified against a live managed database.

## Layer 4 — Production-line editor and Vercel deployment

### Completed

- Added React Flow editing for sources, sinks, machines, buffers, branching/merging routes, rework rules, recipes, operations, multiple resource requirements, and transfer assumptions.
- Added validation for connectivity, ports, capacities, bounded rework, cycles, machine compatibility, required process steps, and invalid transfer assumptions.
- Added undo/redo, immutable version snapshots, history loading, save state, and revision-based optimistic concurrency.
- Added Vercel Services routing: static frontend/landing assets and FastAPI share one deployment origin at `/` + `/app` + `/api/v1`.
- Configured production/preview Celery tasks for Vercel Queues and retained Redis for local Celery and authentication limits.
- Replaced local container configuration with provider-neutral MongoDB, Redis, SMTP, and S3-compatible environment configuration.

### Verification

- `npm run test:backend` — 36 passed, including migrations, organization isolation, graph persistence, snapshot history, stale-write rejection, routing validation, and readiness checks.
- `npm test` — passed; landing-page model, CSV, and demo regressions.
- `npm --prefix frontend test` — passed.
- `npm --prefix frontend run build:vercel` — passed; TypeScript check, production build, and combined landing/application output.
- Verified the combined build output contains the landing root, `/app` entry, and landing favicon.
- Vercel CLI was not installed, so `vercel dev` and an actual deployment were not run. No external service credentials were available for runtime checks.

### Known limitations

- MongoDB transaction behavior, SMTP delivery, storage access, and same-origin routing remain unverified against live services.
- Vercel Queues is beta. The repository currently defines only a health-check task; no production background workflows have been implemented.
- Production still requires external MongoDB with transaction support, TLS Redis, SMTP, and an S3-compatible bucket. Migrations must run explicitly as a serialized release step.
- The editor validates and stores the factory model but does not yet simulate production or calculate validated equipment physics.

### Next layer

Implement only the next layer requested by the user.
