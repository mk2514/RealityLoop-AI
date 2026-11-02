# RealityLoop AI

RealityLoop AI is a manufacturing digital-twin and production-planning application. The approved static landing page remains at `/`; the React application is served under `/app` and FastAPI under `/api/v1`.

## Repository layout

- `dist/` — preserved landing-page assets and browser-local demo.
- `frontend/` — React 19, TypeScript, Vite and Tailwind application.
- `backend/app/` — FastAPI authentication, organization-scoped MongoDB access and Celery worker.
- `backend/app/db/migrations/` — explicit, versioned MongoDB collection-validator/index migrations.
- `backend/tests/` — API and persistence foundation tests.
- `infra/` — local Docker Compose services, Nginx routing and frontend image configuration.
- `tests/` — landing-page model and CSV regression tests.

The application includes email-verified accounts, private workspaces, factory records, and onboarding status. Production integrations and manufacturing workflows are not implemented yet.

## Features

- Two procedural WebGL factory views with orbit, zoom, keyboard view controls, selectable machines, flow playback, top view and an additional parallel drilling station.
- Validated browser-local CSV temperature import and sample export.
- Sensor selection, time ranges, expected and threshold overlays, normalized cross-metric comparison and selected-event context.
- Synthetic calibration example using 40 training and 20 held-out samples.
- Deterministic capacity comparison with demand, downtime, drilling cycles, parallel equipment and disruptions.
- Local demo configuration, decision history, JSON report export, privacy and terms dialogs.
- Argon2 password hashing, verification/recovery emails, opaque server-managed sessions, CSRF protection and Redis-backed authentication rate limits.
- Separate organization records and role-based memberships; factory queries are organization-scoped.
- A persistent, initially empty workspace dashboard with role-aware factory creation and logout.
- Mailpit-based local email testing; production SMTP is configured through environment variables.
- Factory onboarding with timezone, unit preferences and weekly shifts (including overnight shifts).
- Organization-scoped production lines, machines, components and sensors with edit, soft-archive, reopen and audit history.
- Equipment templates and operating-state definitions; templates are metadata suggestions, not validated physics models.
- Measurement-specific sensor unit validation, threshold ordering and calibration metadata.

## Run locally

Requirements: Docker Engine/Desktop with the Docker Compose v2 plugin, Node.js (for a local frontend build), and a terminal.

1. Copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell). Compose explicitly loads this root-level file for every service, even though its YAML is under `infra/`. The example values are for local development only; replace them before sharing the environment.
2. From the repository root, run `docker compose -f infra/docker-compose.yml up --build --wait`.
3. Open `http://localhost:8080/` for the original landing page, `http://localhost:8080/app/` to get started, `http://localhost:8080/app/login` to sign in, or `http://localhost:8080/api/v1/health/ready` for dependency readiness.

Compose starts MongoDB as a single-node replica set (required for transactional account creation), waits for a primary, creates a least-privilege application database user, starts Redis, MinIO and Mailpit, creates the configured MinIO bucket, runs `python -m app.db.migrations.runner` in a one-shot migration service, and then starts the API, Celery worker and Nginx frontend. Migrations are not run on API startup. MongoDB uses an authenticated health check and explicit replica-set initialization instead of startup timing assumptions. The API readiness endpoint also checks the configured SMTP server.

Open `http://localhost:8025/` to inspect verification and password-reset emails sent through Mailpit. The SMTP listener is at `localhost:1025`. Replace the placeholder credentials in `.env` before exposing services beyond the local machine. In production, set `ENVIRONMENT=production`, `COOKIE_SECURE=true`, an HTTPS `PUBLIC_APP_URL`, and SMTP TLS/SSL settings and credentials. Production MongoDB must support transactions (replica set or sharded cluster).

To stop the services while retaining local data, run `docker compose -f infra/docker-compose.yml down`. To remove the local database, Redis and object-storage volumes as well, run `docker compose -f infra/docker-compose.yml down --volumes`; this permanently deletes local development data.

The frontend can also be built without Docker: run `npm --prefix frontend ci` and then `npm run build:frontend`. Run `npm test` for landing-page regression checks. For backend tests on Windows, create `.venv` with `py -3 -m venv .venv`, install dependencies using `.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.lock`, then run `npm run test:backend`. Auth journey tests use `mongomock` and a transaction test double; verify real transaction/migration behavior with the Compose MongoDB replica set when Docker is available. The test script also detects an existing virtual environment on Linux/macOS.

### Migrations

Migrations are versioned in `backend/app/db/migrations/versions/`. They apply strict MongoDB JSON Schema validators and indexes, and record successful versions in `schema_migrations`. Compose runs them as a required one-shot step before the API starts. For an explicit local invocation while Compose dependencies are up, use `docker compose -f infra/docker-compose.yml run --rm migrate`. Re-running the migration runner is safe; it skips completed versions.

### Authentication and workspace

- Registration creates a separate organization and owner membership in one MongoDB transaction. Users must verify their email before login. Verification and password-reset tokens are one-time, expiring, and stored as SHA-256 digests.
- Browser sessions are opaque, stored server-side, expiring and revocable; authentication cookies are HttpOnly and SameSite strict. Unsafe API requests require a CSRF cookie/header pair. Secure cookies and HTTPS are mandatory in production settings.
- Recovery responses do not disclose whether an email is registered. Rate limits use Redis and fail closed when Redis is unavailable.
- Workspace endpoints use the authenticated organization ID in their MongoDB queries. Factory creation is limited to owners, administrators and engineers; operators and viewers have read-only access.
- The preserved public landing-page sample continues to use browser-local demo data. It is not migrated to any account.

### Factory asset registry

The authenticated workspace dashboard contains the factory registry. Create a factory, then add production lines, machines, components and sensors from their parent records. Templates prefill descriptive capabilities only; machine physics remain explicitly unvalidated. Archives are soft, cascade to descendants, and can be reopened in parent-first order. Important changes are written to the organization-scoped asset audit log. Migration `0003_factory_assets` applies collection validators and organization-scoped identity indexes, and adds default settings for existing factory documents.

### Local development endpoints

- Mailpit inbox: `http://localhost:8025`; SMTP: `localhost:1025`.
- MinIO API: `http://localhost:9000`; console: `http://localhost:9001`.
- MongoDB: `localhost:27017`; Redis: `localhost:6379`.
- API liveness: `/api/v1/health/live`.
- API readiness: `/api/v1/health/ready` (returns `503` until MongoDB, Redis and MinIO are reachable).

## Production deployment

Static hosting alone cannot run this application stack. A production deployment needs separately operated MongoDB, Redis, a durable S3-compatible object store, an API service, a Celery worker, and a reverse proxy or ingress that routes `/`, `/app`, and `/api/v1` on one HTTPS origin. Apply MongoDB schema migrations as an explicit, serialized release step before deploying compatible API versions. Use managed secrets and a least-privilege application database user (not the local MongoDB root account), encrypted transport, backups, monitoring, worker scaling, object-store lifecycle/permissions, and organization-scoped authorization before accepting customer or machine data. The local Compose credentials and HTTP-only configuration are not production-ready.

The MongoDB identity model uses separate organization, user, and organization-membership collections. Unique indexes enforce organization slugs, user emails, and one membership per organization/user pair. The explicit `0002_authentication` migration adds password and verification fields, role names, sessions, tokens and factories with strict collection validators and expiry indexes.

## Scope

The preserved landing page is a browser-local demonstration, not a production manufacturing backend. Application foundation, Layer 2 authentication/workspace flows, and Layer 3 factory onboarding/asset registry are implemented. Sensor ingestion, real machine connections, versioned production models, simulation, forecasts and decision workflows remain unimplemented.

No user data is sent to an application server by this page. Demo configuration and decision history use localStorage, while imported readings remain in memory. Read the page privacy notice for hosting limitations.

## Drafting style and motion

Machines use ivory surfaces, screen-space pencil hatching, crisp ink outlines, faint hidden edges, construction guides and projected station labels. Factory assembly draws on once, camera changes ease between views, and charts reveal their observed curve. Page effects can be paused globally. System reduced-motion preferences disable automatic motion. Offscreen scenes skip rendering and animation advances only while visible.
