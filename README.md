# RealityLoop AI

RealityLoop AI is a manufacturing digital-twin and production-planning application. Layer 1 keeps the approved static landing page intact at `/` and adds the React application at `/app` and FastAPI at `/api/v1`.

## Repository layout

- `dist/` — preserved landing-page assets and browser-local demo.
- `frontend/` — React 19, TypeScript, Vite and Tailwind application.
- `backend/app/` — FastAPI, PyMongo organization/user document models and Celery worker.
- `backend/app/db/migrations/` — explicit, versioned MongoDB collection-validator/index migrations.
- `backend/tests/` — API and persistence foundation tests.
- `infra/` — local Docker Compose services, Nginx routing and frontend image configuration.
- `tests/` — landing-page model and CSV regression tests.

The application screen is intentionally a setup-status screen. It does not imply that sign-in, a factory workspace, or production integrations exist yet.

## Features

- Two procedural WebGL factory views with orbit, zoom, keyboard view controls, selectable machines, flow playback, top view and an additional parallel drilling station.
- Validated browser-local CSV temperature import and sample export.
- Sensor selection, time ranges, expected and threshold overlays, normalized cross-metric comparison and selected-event context.
- Synthetic calibration example using 40 training and 20 held-out samples.
- Deterministic capacity comparison with demand, downtime, drilling cycles, parallel equipment and disruptions.
- Local demo configuration, decision history, JSON report export, privacy and terms dialogs.

## Run locally

Requirements: Docker Engine/Desktop with the Docker Compose v2 plugin, Node.js (for a local frontend build), and a terminal.

1. Copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell). The example values are for local development only; replace them before sharing the environment.
2. From the repository root, run `docker compose -f infra/docker-compose.yml up --build --wait`.
3. Open `http://localhost:8080/` for the original landing page, `http://localhost:8080/app/` for the application foundation, or `http://localhost:8080/api/v1/health/ready` for dependency readiness.

Compose starts MongoDB, Redis and MinIO; creates the configured MinIO bucket; runs `python -m app.db.migrations.runner` in a one-shot migration service; then starts the API, Celery worker and Nginx frontend. The API does not run schema changes on startup. It waits for the migration service to complete successfully. MongoDB uses an authenticated `mongosh` ping health check rather than a fixed startup delay.

To stop the services while retaining local data, run `docker compose -f infra/docker-compose.yml down`. To remove the local database, Redis and object-storage volumes as well, run `docker compose -f infra/docker-compose.yml down --volumes`; this permanently deletes local development data.

The frontend can also be built without Docker: run `npm --prefix frontend ci` and then `npm run build:frontend`. Run `npm test` for landing-page regression checks. For backend tests on Windows, create `.venv` with `py -3 -m venv .venv`, install dependencies using `.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.lock`, then run `npm run test:backend`. The test script also detects an existing virtual environment on Linux/macOS.

### Migrations

Migrations are versioned in `backend/app/db/migrations/versions/`. They apply strict MongoDB JSON Schema validators and indexes, and record successful versions in `schema_migrations`. Compose runs them as a required one-shot step before the API starts. For an explicit local invocation while Compose dependencies are up, use `docker compose -f infra/docker-compose.yml run --rm migrate`. Re-running the migration runner is safe; it skips completed versions.

### Local development endpoints

- MinIO API: `http://localhost:9000`; console: `http://localhost:9001`.
- MongoDB: `localhost:27017`; Redis: `localhost:6379`.
- API liveness: `/api/v1/health/live`.
- API readiness: `/api/v1/health/ready` (returns `503` until MongoDB, Redis and MinIO are reachable).

## Production deployment

Static hosting alone cannot run this application stack. A production deployment needs separately operated MongoDB, Redis, a durable S3-compatible object store, an API service, a Celery worker, and a reverse proxy or ingress that routes `/`, `/app`, and `/api/v1` on one HTTPS origin. Apply MongoDB schema migrations as an explicit, serialized release step before deploying compatible API versions. Use managed secrets and a least-privilege application database user (not the local MongoDB root account), encrypted transport, backups, monitoring, worker scaling, object-store lifecycle/permissions, and organization-scoped authorization before accepting customer or machine data. The local Compose credentials and HTTP-only configuration are not production-ready.

The identity foundation uses separate organization, user, and organization-membership collections: memberships reference organizations and users to support unbounded and many-to-many relationships without growing embedded arrays. Unique indexes enforce organization slugs, user emails, and one membership per organization/user pair. Authentication is intentionally not exposed yet.

## Scope

The preserved landing page is a browser-local demonstration, not a production manufacturing backend. The new API currently provides health/readiness endpoints and database schema foundations only. Authentication, verification, organization-scoped API permissions, factory models, sensor ingestion, real machine connections, simulation, forecasts and decision workflows are not implemented in Layer 1.

No user data is sent to an application server by this page. Demo configuration and decision history use localStorage, while imported readings remain in memory. Read the page privacy notice for hosting limitations.

## Drafting style and motion

Machines use ivory surfaces, screen-space pencil hatching, crisp ink outlines, faint hidden edges, construction guides and projected station labels. Factory assembly draws on once, camera changes ease between views, and charts reveal their observed curve. Page effects can be paused globally. System reduced-motion preferences disable automatic motion. Offscreen scenes skip rendering and animation advances only while visible.
