# Build progress

## MetroPT3 historical replay demo

### Completed

- Added a bounded 218-row MetroPT3 source subset fixture with the original header and source-record index under `backend/tests/fixtures/sensor-imports/metropt3_demo.csv`; the full raw CSV remains untracked.
- Added `MetroReplay` to the saved-machine dashboard with CSV timestamp validation, source-window selection, TP3/current/COMP synchronized replay, tenant-scoped importer mapping and traceable evidence.
- Added a MetroPT-3 preset to the existing sensor importer for `TP3`, `Motor_current`, `COMP`, timestamp timezone and fixed units.
- Added past-only held-out TP3 comparison using the last-value baseline, explicit sample size and absolute error.
- Added an organization-scoped, worker-queued Gemini evidence-analysis endpoint. The worker receives only a bounded evidence summary, not raw readings.
- Added missing-key/provider-outage numerical fallbacks and documented COMP=1 semantics.

### Verification

- Raw MetroPT3 streaming found 1,516,948 rows; timestamps from `2020-02-01 00:00:00` through `2020-09-01 03:59:50`; no invalid timestamps; the observed cadence is predominantly 10 seconds.
- The bounded fixture covers source-record IDs 1400 through 3570 and timestamps `2020-02-01 00:23:08` through `2020-02-01 00:58:58`.
- `python -m pytest backend/tests/test_sensor_imports.py -q`: 13 passed.
- Frontend production build and Vitest regression run passed: 2 test files, 5 tests; model/CSV validation checks passed.
- Browser click path, live MongoDB/Celery/Redis storage, provider Gemini and hardware replay are pending credentials/services.

## Twin validation for saved line versions

### Completed

- Added `0014_twin_validations` MongoDB collection and organization-scoped indexes.
- Added pinned saved-version validation requests for completed simulation runs.
- Validation pins the simulation snapshot/hash, recipe, product, line-version snapshot, sensor mapping, timezone, independent calibration and observation windows, feed conditions and data-quality rules.
- Conveyor exit-count validation compares pinned simulated cycle completions with independent observed counter readings.
- Detection includes cumulative/incremental counters, counter resets, missing intervals, duplicate timestamps, incompatible units and insufficient ground truth.
- Metrics report sample size, coverage, signed bias (`simulated - observed`), absolute error, units and evidence source.
- Added the `Validate this twin` workflow to saved-version review with status and metric-specific evidence.
- Historical validations are immutable records; live asset recalibration or line edits do not alter completed results.

### Verification

- `backend/tests/test_twin_validation.py` passed the hand-calculated conveyor fixture: 15 observed exits, 18 simulated exits, bias 3, absolute error 3.
- Missing-ground-truth fixture passed as `insufficient_evidence`.
- Migration and simulation regressions passed: 8 focused tests passed.
- Frontend TypeScript/Vite production build passed.

### Known limitations

- Cycle-time and queue-wait validation requires station-specific independent observations and is not yet accepted by the conveyor gate.
- The UI currently supplies exit-count sensor ID and independent windows explicitly; automatic station/feed discovery is not implemented.
- Live MongoDB, Celery execution, managed object storage, browser rendering and Render/Vercel deployment were not verified with provider credentials.

## Layer 12 — Organization-scoped scenario comparison (implemented, acceptance verification in progress)

### Completed

- Added organization-scoped scenario forks, immutable baseline/candidate snapshots, chaos profiles and paired scenario comparisons using the existing pinned SimPy engine.
- Added parallel-equipment resource quantities and bounded candidate/resource validation.
- Added scenario, scenario run, comparison and chaos-profile MongoDB migrations and indexes.
- Wired the scenario workspace into `/app/dashboard`; all values are labeled as simulated and expose seed, replications, confidence interval and bottleneck output.
- Candidate changes send no machine commands and do not alter live factory or line documents.

### Verification

- Frontend Vite/TypeScript production build passed.
- Backend regression suite passed 57 tests after migration registration.
- Layer 12 focused scenario and routing validation assertions were added; run them before the acceptance gate.
- Managed MongoDB, live server-side cross-organization HTTP access, browser rendering and provider deployment credentials remain unverified.

## Layer 9 — Machine and sensor dashboards (in progress)

### Completed

- Added an organization-scoped dashboard hierarchy for factory → line → machine → component → sensor.
- Added bounded raw and server-side bucketed observed-reading APIs, canonical UTC storage, provenance drill-down, CSV export, display timezone/unit conversion, sensor freshness and gap metadata.
- Added Apache ECharts to `/app/dashboard`, synchronized chart controls, gap-safe null series and saved per-user panel layouts.
- Added versioned threshold-rule storage, station-to-sensor overlay mappings and simulation-overlay eligibility checks.
- Added MongoDB migration `0009_dashboards`.

### Verification

- Backend gate suite passed 57 tests after the Layer 9 implementation additions.
- Frontend production build passed.
- Live MongoDB, managed provider credentials, ECharts browser rendering and cross-tenant dashboard HTTP calls remain to be verified with provider credentials.

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

## Layer 6 — Local integration smoke gate

### Completed

- Added a no-container local integration runner using native/host services configured by the existing root `.env` variables. It refuses non-loopback MongoDB, Redis, SMTP, object-storage, or app URL targets to prevent accidental writes to shared or production systems.
- Added a Playwright journey for registration, Mailpit email verification, single-use token rejection, sign-in, dashboard access, factory/line/machine/component/sensor creation, immutable line-version persistence, and 3D review with WebGL unavailable.
- The browser journey attempts guessed factory, machine, and saved-version IDs from a separately registered organization and requires 404 denial.
- Added real-service logout/session revocation and protected dashboard checks (401 after logout).
- The runner applies migrations twice and requires the second run to be a no-op, starts the API, Celery worker and Vite locally, checks readiness, and verifies a Redis-to-worker task round trip.
- Documented local native-service setup and a separate staging checklist for credentialed CORS and `SameSite=Strict` cookies. No deployment or paid provisioning was performed.

### Verification

- `npm --prefix frontend ci` — passed; lockfile install completed and npm reported 0 vulnerabilities.
- `npm test` — passed; TypeScript check and production build, 2 Vitest files / 5 tests, plus demo model and CSV checks.
- `npm run test:backend` — passed; 38 tests, with 103 existing dependency deprecation warnings.
- `npm --prefix frontend run test:smoke -- --list` — passed; the end-to-end scenario is discoverable.
- The local-only guard rejected a multi-host Mongo URI containing a remote host before running migrations.
- Full local smoke test was not run: native MongoDB, Redis, Mailpit, MinIO and `mc` executables are not installed/on PATH here, and Playwright has no registered Chromium browser. No service-backed acceptance is marked passed.
- No sensor telemetry ingestion or readings are generated by this smoke test; the saved-version inspector explicitly identifies that it contains no live telemetry.

### Known limitations and next layer

- The local smoke test leaves its uniquely named test records in the configured local database; do not use it against shared or production services.
- Staging CORS/cookie checks require actual staging domains and credentials and remain unverified.
- Telemetry ingestion and monitoring are not implemented by this integration gate; continue only when that layer is explicitly requested.

## Layer 6 — Historical sensor imports

### Completed

- Added the versioned `NormalizedReadingV1` contract, explicit quantity/unit conversions, UTC normalization with DST ambiguity/nonexistent-time rejection, calibration handling and deterministic SHA-256 event keys.
- Added migration `0006_sensor_readings` with tenant-scoped unique event-key, sensor/event-time, import, and per-import row-result indexes.
- Added cookie/CSRF/role-protected CSV preview, mapping and confirmation endpoints; bounded UTF-8 uploads; private S3-compatible source/error files; checksum verification; and short-lived organization-authorized error downloads.
- Added a streaming Celery import task with batch transactions, progress/status counts, stable row rejection codes, duplicate classification, retry idempotency, cancellation and source checksum verification.
- Added the per-sensor `/app` import UI with mapping preview, live status refresh, duplicate notices, error CSV download, cancel and retry actions.
- Added exact fixture counts, retry, checksum, private object, DST, unit, file-size, row error, no-embedded-reading and cross-organization tests.
- Added a Render worker service definition for the existing Python/Celery stack; it shares the configured backend environment and does not add Docker or provision services.
- Documented the reading contract, key semantics, mapping, privacy, retries, limits and local worker/API commands in `docs/SENSOR_IMPORTS.md` and `README.md`.

### Verification

- Layer 6 focused gate: `backend/tests/test_sensor_imports.py` — 4 passed, 0 failed. Fixture result: expected 8 rows / 1 inserted / 2 duplicates / 5 rejected; actual matches exactly. Rejected: `MALFORMED_ROW` 1, `UNKNOWN_SENSOR` 1, `BAD_TIMESTAMP` 1, `NON_NUMERIC_VALUE` 1, `INCOMPATIBLE_UNIT` 1.
- Retry/redelivery test: reading collection remained at 2 total (1 seeded existing + 1 inserted); all 8 row outcomes and import counts stayed unchanged.
- Frontend production TypeScript/Vite build passed after adding the sensor import screen.
- The test suite uses MongoDB transaction and S3 storage doubles. Live MongoDB replica-set transactions, Render Redis/Celery, S3-compatible bucket policies/encryption and presigned downloads have not been verified.

### Known limitations and deferred layers

- Layer 7 device credentials, live REST/MQTT/OPC UA ingestion, durable edge buffering and stale-sensor state have not started; credential-model and protocol-fixture docs will accompany that gated layer.
- Layer 8 simulation, immutable run pinning and replay have not started; their pinning/event-log documentation will accompany that gated layer.
- Local interactive imports require configured MongoDB, Redis, worker and private S3-compatible storage. No deployment, hardware integration, machine actuation or Docker environment was introduced.

## Layer 8 — Production simulation and replay

### Completed

- Added migration `0008_simulation_runs` and organization-scoped simulation run/event collections and indexes.
- Added immutable run snapshot pinning for line models, resolved machine parameters, factory calendar/timezone, recipe/product, assumptions, seed and run limits.
- Added snapshot validation, SimPy execution, Celery lifecycle/status handling, cancellation checks, retry idempotency, persisted metrics and bounded paginated replay events.
- Added `/app/dashboard` simulation run controls and a separate stored-event replay mode in the saved-version review.
- Added deterministic fixture tests and simulation pinning/validation coverage.

### Verification

- Frontend production build passed.
- Frontend test suite passed 5 tests plus model/CSV checks.
- Backend suite: 54 passed, 0 failed, including migration `0008`, the deterministic Layer 8 fixture, seed behavior and snapshot pinning validation.
- Lockfile dev environment regenerated to include pinned SimPy 4.1.1; runtime dependency installation verified.
- Live Celery/Redis, managed MongoDB, Render worker execution, browser replay rendering and deterministic provider hardware remain unverified.

### Known limitations

- Simulation is limited to the existing deterministic/explicitly declared cycle-time concepts; unsupported distributions and missing routing parameters fail validation.
- This layer provides replay of stored events and does not issue equipment commands.
