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
- Initially configured Vercel Services for a same-origin full stack; that deployment approach was replaced by the split Vercel + Render architecture below.
- Configured Celery with Redis as the broker; the worker is deployed separately from the API.
- Replaced local container configuration with provider-neutral MongoDB, Redis, SMTP, and S3-compatible environment configuration.

### Verification

- `npm run test:backend` — 36 passed, including migrations, organization isolation, graph persistence, snapshot history, stale-write rejection, routing validation, and readiness checks.
- `npm test` — passed; landing-page model, CSV, and demo regressions.
- `npm --prefix frontend test` — passed.
- The original combined Vercel build passed at delivery; its copy-based packaging step is superseded by the unified build documented below.
- Verified the combined build output contains the landing root, `/app` entry, and landing favicon.
- Vercel CLI was not installed, so `vercel dev` and an actual deployment were not run. No external service credentials were available for runtime checks.

### Known limitations

- MongoDB transaction behavior, SMTP delivery, and storage access remain unverified against live services.
- The initial Vercel Queues configuration was removed in the split-deployment update. Render runs a Redis-backed worker, but no production background workflows beyond the health-check task have been implemented.
- Production still requires external MongoDB with transaction support, TLS Redis, SMTP, and an S3-compatible bucket. Migrations must run explicitly as a serialized release step.
- The editor validates and stores the factory model but does not yet simulate production or calculate validated equipment physics.

## Layer 5 — Saved-version 3D review

### Completed

- Added a Three.js orthographic/isometric review and top view generated only from immutable saved line-version snapshots.
- Added template-specific equipment geometry for conveyors, processing stations, CNC/cutting, drilling, assembly, inspection, packaging, buffer/storage, source/sink, and custom stations.
- Generated static material connections, buffers, parallel stations, construction guides, and drafting hatching from the saved graph. Flow is explicitly illustrative; no operational or simulated movement is shown.
- Added orbit/zoom/reset controls, accessible machine selection, synchronized 2D/3D selection, and an inspector backed by the stored machine and component records.
- Added a WebGL-unavailable SVG schematic fallback while preserving the 2D editor and asset inspection. Added a global animation pause control and retained reduced-motion support.

### Verification

- `npm test` — includes TypeScript production build, WebGL-disabled fallback and keyboard-selection tests, saved-model update rendering, and landing-page regression tests.
- `npm run test:backend` — 38 passed after adding split-deployment origin validation.
- The production build passed; landing root, `/app` entry, landing favicon, and lazy 3D-review chunk were present in the combined output.
- `npm audit` — 0 frontend dependency vulnerabilities.
- The 3D review chunk is 524 KB minified (133 KB gzip) and is loaded on demand; Vite reports its standard 500 KB chunk-size warning.
- Vercel CLI deployment, physical WebGL hardware/browser rendering, and managed-service checks remain unverified.

### Known limitations

- Geometry is a review visualization only, not a validated physics model or operational simulation.
- The 3D view requires WebGL; browsers without it receive a static, selectable SVG schematic and can return to 2D editing.
- Machine/component details reflect current organization-scoped asset records, while layout and connections come from the selected immutable line snapshot.

## Deployment architecture update — Vercel frontend + Render backend

### Completed

- Changed Vercel to build and serve only the preserved landing page and React `/app` output.
- Added Render Blueprint definitions for the FastAPI web service and Redis-backed Celery worker, sharing a private environment-variable group.
- Made the frontend API base URL an optional Vercel build-time setting and enabled explicit credentialed CORS origins in FastAPI.
- Documented that production frontend/API domains must be HTTPS subdomains of one registrable domain to preserve current `SameSite=Strict` authentication cookies.
- Added production config validation for explicit HTTPS frontend origins and frontend validation of any supplied API URL; frontend-only builds may leave it unset.
- Updated the credential setup guide; secrets are to be entered only into local ignored `.env` and provider environment settings.

### Pending

- User must provision MongoDB, TLS Redis, SMTP and S3-compatible storage, configure custom frontend/API domains, and enter provider credentials before live connectivity can be tested.
- Frontend tests/build and backend unit/integration tests pass; Vercel and Render deployments, provider blueprint validation, production migrations, and cross-origin cookie/auth flows have not been run.
- Applying the Render Blueprint uses Starter services; review Render's current pricing and approve charges before provisioning.

## Architecture follow-up — unified frontend (current)

### Completed

- Migrated the landing page markup, styles, Three.js factory, controls, demo logic, assets, and license into `frontend/src/landing/`; retained its browser-local storage keys and sample behavior.
- Combined the public page and React application into one Vite document/root/router. `/` serves the landing page and `/app` serves the application; app subroutes preserve query parameters for verification and reset links.
- Scoped landing CSS and DOM interactions to the mounted landing component, with cleanup on route changes. App styles, React Flow, and 3D review remain available.
- Removed the old root `dist/` source tree and copy-based `frontend/scripts/build-vercel.mjs` after verifying the migrated page and build. `frontend/dist/` is now the sole generated production output.
- Configured Vercel to install via the frontend lockfile, build once, serve `frontend/dist`, rewrite only `/app` routes, and leave `/api/v1` out of the frontend fallback.
- Made `VITE_API_BASE_URL` optional for frontend-only deployment. An explicitly supplied invalid value fails validation; an unset value leaves public navigation and the browser-local demo usable and reports backend-dependent actions as unavailable.
- Preserved the local Vite `/api/v1` proxy and documented the one frontend setting to add after Render is deployed.

### Verification

- `npm --prefix frontend ci` — passed; lockfile install completed with no reported dependency vulnerabilities.
- `npm --prefix frontend test` — passed; TypeScript check/build, 2 Vitest files (5 tests), and the existing demo-model/CSV checks.
- `VERCEL=1 npm --prefix frontend run build` with `VITE_API_BASE_URL` unset — passed.
- The same production build with `VITE_API_BASE_URL=https://api.example.com/api/v1` — passed. This is a format check only, not a live API.
- The environment validator accepted an unset and valid HTTPS API base and rejected an invalid value.
- Local production preview checks covered `/`, `/app`, direct `/app` auth subroutes and query tokens, app navigation/history, responsive layout, reduced motion, demo configuration persistence, 3D canvases and controls, CSV import, and the explicit unavailable-backend state. No browser page errors or failed static-asset requests were observed.
- Local `/api/v1` preview with no backend returned a plain-text 500 rather than the React document. The Vercel routing configuration contains no API rewrite.

### Known limitations

- Vercel CLI/deployment was not available; Vercel-specific rewrite behavior and a deployed site were not exercised. Local preview and build configuration were checked separately.
- Render and its dependent MongoDB, Redis, SMTP, and object-storage services are not deployed or connected. No real account, saved workspace, or backend response was asserted.
- When Render is ready, set `VITE_API_BASE_URL=https://<Render API domain>/api/v1` in Vercel's build environment and rebuild/redeploy.

### Next layer

Implement only the next layer requested by the user.
