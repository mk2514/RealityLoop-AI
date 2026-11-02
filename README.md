# RealityLoop AI

RealityLoop AI is a manufacturing digital-twin and production-planning application. The approved landing page is served at `/`, the React application at `/app`, and FastAPI exposes `/api/v1`.

## Repository layout

- `frontend/index.html` — the single document entry point for the public page and application.
- `frontend/src/landing/` — migrated landing markup, scoped styles, browser-local demo logic, Three.js factory scene, assets and license.
- `frontend/src/` — shared React router and the `/app` React, TypeScript, Tailwind, React Flow and Three.js application.
- `frontend/dist/` — generated production build output; do not edit.
- `backend/app/` — FastAPI, organization-scoped MongoDB access, explicit migrations and Celery.
- `backend/tests/` — API, persistence and migration tests.
- `vercel.json` — one static Vite build and `/app` route rewrites for Vercel.
- `render.yaml` — optional, separately deployed Render API and Celery worker for the later backend deployment step.
- `docs/BUILD_PROGRESS.md` — delivered layers, checks and known limitations.

The public landing page and browser-local sample demo are separate from signed-in workspaces; their browser data is never imported into an account.

## Implemented

- Preserved interactive, reduced-motion-aware landing page and sample demonstration.
- Email verification and recovery, server-side sessions, CSRF protection, rate limits and organization roles.
- Organization-isolated factory, line, machine, component and sensor registry with audit history.
- Persistent production-line editor with validation, immutable snapshots and optimistic concurrency.
- Saved-version 3D review with template geometry, synchronized selection and an accessible schematic fallback without WebGL. Material paths are illustrative, not simulated job movement.
- MongoDB collection validators and explicit, idempotent migrations.
- One frontend at `/` and `/app`, deployable as a single Vercel static project. The backend remains a separate service for a later deployment step.

Equipment templates are descriptive only. Live machine integration, telemetry ingestion, production simulation, forecasts and validated equipment physics are not implemented yet.

## Local development

No Docker or Vercel CLI is required to run the frontend or browser-local landing demo. Start the unified Vite app from the repository root:

```sh
npm --prefix frontend ci
npm run dev:frontend
```

Open `http://localhost:5173`. The landing page, public sample and application routes all run through this one frontend server. The Vite proxy keeps `/api/v1` pointed at `http://127.0.0.1:8001`; backend-dependent actions show an unavailable-service message if FastAPI is not running. `VITE_API_BASE_URL` is optional and defaults to the local proxy path.

To exercise the backend locally, configure its services in a root `.env` copied from `.env.example`. MongoDB must support transactions. For local email testing, run the standalone [Mailpit binary](https://mailpit.axllent.org/docs/install/); its defaults match the example SMTP configuration. Install and start the backend separately:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.lock
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
```

Run database migrations explicitly from the repository root, using the same `.env`:

```powershell
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -m app.db.migrations.runner
```

Migrations are idempotent and do not run automatically during startup or deployment.

## Vercel frontend deployment (current step)

The frontend builds and deploys independently. No backend URL, API credential, or backend service is needed to serve `/`, the public sample demo, or the `/app` welcome screen. Until a backend is connected, backend-dependent actions show a clear unavailable-service message.

In Vercel, import the repository with these settings:

| Setting | Value |
|---|---|
| Root Directory | `.` (repository root) |
| Install Command | `npm --prefix frontend ci` |
| Build Command | `npm --prefix frontend run build` |
| Output Directory | `frontend/dist` |
| Environment Variables | None required for frontend-only deployment |

These settings are also recorded in [`vercel.json`](./vercel.json). The only configured rewrites are `/app` and `/app/*` to the single `index.html`; static assets keep their real paths and `/api/v1` is not rewritten to the React page. Leave `VITE_API_BASE_URL` unset until the backend is deployed. When Render is ready, add `VITE_API_BASE_URL=https://api.example.com/api/v1` as a Vercel **build** environment variable and redeploy; it is a public URL, not a secret.

## Later: Render backend and service credentials

The Render API and Celery worker are independent services. When preparing that later deployment, use the backend setup and credential requirements below. To keep the current `SameSite=Strict` session and CSRF cookies reliable, use HTTPS custom domains on the same registrable domain, for example `app.example.com` on Vercel and `api.example.com` on Render. The default `*.vercel.app` and `*.onrender.com` addresses are different sites and are not a supported production authentication pairing.

1. Provision the services listed under [Required credentials and service settings](#required-credentials-and-service-settings). MongoDB must support transactions; Redis must provide a TLS `rediss://` URL.
2. Apply [`render.yaml`](./render.yaml) as a Render Blueprint; configure the required environment variables separately on both the API and worker services, then configure the custom API domain.
3. Run migrations once as a serialized release step. In Render Shell, install `requirements.lock` from the `backend` root and run `python -m app.db.migrations.runner`.
4. Configure the Vercel `VITE_API_BASE_URL` value above, and set `PUBLIC_APP_URL` and `FRONTEND_ORIGINS` to the final HTTPS frontend origin in Render.
5. Test registration, verification, login, logout and protected requests against the deployed services. API readiness remains unavailable until its required services connect.

Render, MongoDB, Redis, mail and object storage are independently provisioned; the repository does not create accounts or provision paid services.

### Required credentials and service settings

These are **later backend service credentials/settings, not a collection of AI API keys**. The implemented product does not call an LLM or other AI vendor. Do not send passwords, URIs, access keys or tokens in chat; enter them directly into your local ignored `.env` or Render's private environment-variable UI.

| Variable(s) | Needed for | How to obtain/configure |
|---|---|---|
| `MONGO_URI`, `MONGO_DATABASE` | Render API, worker and migrations | Create a MongoDB Atlas cluster with transaction support, create a least-privilege application database user, allow Render service egress in the Atlas network access list, and copy the authenticated `mongodb+srv://` URI. Set database name to `realityloop` unless choosing another consistently. |
| `REDIS_URL` | Render API, Celery worker and auth rate limits | Provision a reachable TLS Redis-compatible service and use its `rediss://` connection URL. The deployed API and worker must use the same Redis database/broker. |
| `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Render API readiness and future object storage | Create a private bucket in AWS S3 or another S3-compatible provider. Create bucket-scoped credentials with only necessary access; `HeadBucket` must succeed. |
| `S3_ENDPOINT_URL` | Render API, only for non-AWS S3-compatible storage | Copy the provider's HTTPS S3 endpoint. Leave empty for AWS S3. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER`, `SMTP_STARTTLS`, `SMTP_SSL` | Render API account verification and recovery email | Create SMTP credentials with an email provider. Obtain its host, port, username/password and verified sender address. Use STARTTLS or SSL; do not enable both. |
| `PUBLIC_APP_URL` | Render API email links | Set to the deployed HTTPS frontend origin, e.g. `https://app.example.com`. |
| `FRONTEND_ORIGINS` | Render API credentialed CORS | Set the exact comma-separated HTTPS frontend origin(s), e.g. `https://app.example.com`; no wildcard. Keep frontend and API on HTTPS subdomains of the same registrable domain for `SameSite=Strict` auth cookies. |
| `VITE_API_BASE_URL` | Vercel frontend build, only after Render is ready | Set to the API URL including prefix, e.g. `https://api.example.com/api/v1`. This is not a credential and can be visible in browser assets. |
| `ENVIRONMENT=production`, `COOKIE_SECURE=true` | Render API and worker | Set directly in each Render service's environment settings. Keep secure cookies enabled. |

The Blueprint does not define or attach a shared environment group. Enter the applicable values from this table directly in the Render API and worker environment settings; keep credentials out of Git. For local testing, use `.env.example` as the root `.env` template. Rotate any credentials that were accidentally committed or shared.

No Vercel token, Render API key, browser API key, or separate session-signing key is needed for Git-connected deployments and the current application. Platform API tokens are only needed if you later automate deployments outside the provider's Git integration. Do not provide AI provider keys unless a future layer explicitly adds an AI-backed feature.

## Tests and verification

```powershell
npm test
npm run test:backend
npm run build:frontend
npm --prefix frontend run build
```

Backend tests use `mongomock` and transaction doubles; they do not prove live MongoDB transactions, Render connectivity, SMTP delivery, or browser cookie behavior in production. See [`docs/BUILD_PROGRESS.md`](./docs/BUILD_PROGRESS.md) for layer-specific checks and limitations.
