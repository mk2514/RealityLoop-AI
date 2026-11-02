# RealityLoop AI

RealityLoop AI is a manufacturing digital-twin and production-planning application. The approved landing page remains at `/`, the React application at `/app`, and FastAPI at `/api/v1`.

## Repository layout

- `dist/` — preserved landing-page assets and browser-local sample demo.
- `frontend/` — React, TypeScript, Vite, Tailwind and the React Flow production-line editor.
- `backend/app/` — FastAPI, organization-scoped MongoDB access, explicit migrations and Celery configuration.
- `backend/tests/` — backend API, persistence and migration tests.
- `vercel.json` — Vercel Services routing and per-service build configuration.
- `docs/BUILD_PROGRESS.md` — delivered layers, checks and known limitations.

The local landing demo is a separate browser-only experience; its data is not imported into a real account.

## Implemented

- Preserved interactive, reduced-motion-aware landing page and its sample demonstration.
- Email verification and recovery, server-side sessions, CSRF protection, rate limits and organization roles.
- Organization-isolated factory, production-line, machine, component and sensor registry with audit history.
- Persistent 2D production-line graphs with explicit sources/sinks, branching, buffers, recipes, operation compatibility, transfer assumptions, validation, undo/redo, immutable versions and optimistic concurrency.
- MongoDB collection validators and explicit, idempotent migrations.
- Vercel Services configuration for the static frontend and FastAPI backend on one deployment origin.

The equipment templates are descriptive only. No live machine integration, telemetry ingestion, simulation, ML forecast or validated equipment physics is included yet.

## Run locally

The application no longer uses Docker. Install Node.js, Python, the Vercel CLI (58.9.0 or newer), and configure reachable MongoDB, Redis, SMTP and S3-compatible services. MongoDB must support transactions (a replica set or sharded cluster).

1. Copy `.env.example` to `.env` and set credentials and URLs for your development services. Do not commit `.env`.
2. From the repository root, install backend/frontend dependencies and start the Vercel Services project:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.lock
   $env:PYTHONPATH = "$PWD\backend"
   npm --prefix frontend ci
   npx vercel dev
   ```

3. Open the local URL reported by Vercel. The original landing page is `/`, the application is `/app/`, and API readiness is `/api/v1/health/ready`.

Local readiness returns `503` until MongoDB, Redis, the configured storage bucket and SMTP are reachable. These dependencies are not bundled. For local email testing, run the standalone [Mailpit binary](https://mailpit.axllent.org/docs/install/) in another terminal; the example SMTP settings target its default listener. View captured mail at `http://localhost:8025`.

### Environment and services

`.env.example` documents the variables used by the API. Configure:

- `MONGO_URI` and `MONGO_DATABASE` for a MongoDB deployment that supports transactions.
- `REDIS_URL` for Redis; use `rediss://` for production.
- `S3_BUCKET`, `S3_REGION`, optional `S3_ENDPOINT_URL`, and access credentials for S3-compatible storage. Readiness verifies access with `HeadBucket`.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_SENDER`, optional credentials, and either STARTTLS or SSL in production.
- `PUBLIC_APP_URL`, `COOKIE_SECURE=true`, and `ENVIRONMENT=production` for a production deployment.

In Vercel, configure these as encrypted project/service environment variables, not in source control. Preview deployments must also use secure cookies, HTTPS, and production-grade dependencies. Verify your SMTP provider permits connections from Vercel.

### Database migrations

Migrations are versioned in `backend/app/db/migrations/versions/`; they apply strict MongoDB validators and indexes and record applied versions. Migrations never run automatically during API startup or a frontend build. Run them explicitly as a serialized release step after setting the same database environment variables used by the API:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.lock
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -m app.db.migrations.runner
```

Re-running the migration command is safe; completed versions are skipped. In CI, provision the release environment with the deployment's database secret before running this command.

## Vercel deployment

Connect this repository to Vercel with the repository root as the project root and use the checked-in [`vercel.json`](./vercel.json). The frontend service builds the preserved landing assets together with the `/app` Vite output; the backend service exposes the FastAPI application under `/api/v1`. Both routes share one deployment origin, so the existing cookie and CSRF flows remain same-origin.

Set the environment variables above in Vercel, ensure the MongoDB cluster allows Vercel connections, and run migrations explicitly before deploying code that depends on a new schema. Celery uses Vercel Queues in preview/production (currently a Vercel beta); local development uses Redis as the Celery broker. The repository currently defines only a health-check task, not production background workflows. Authentication rate limiting continues to use Redis.

After linking the repository and setting deployment secrets, deploy with `npx vercel@latest --prod`. For a preview deployment, omit `--prod`.

MongoDB, Redis, SMTP and S3-compatible storage remain externally managed services; Vercel does not provision them through this repository.

## Checks

```powershell
npm test
npm run test:backend
npm run build:frontend
npm --prefix frontend test
```

Backend tests use `mongomock` and a transaction test double. They do not prove live MongoDB transaction behavior. See [`docs/BUILD_PROGRESS.md`](./docs/BUILD_PROGRESS.md) for per-layer verification and limitations.
