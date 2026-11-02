# RealityLoop AI

RealityLoop AI is a manufacturing digital-twin and production-planning application. The approved landing page is served at `/`, the React application at `/app`, and FastAPI exposes `/api/v1`.

## Repository layout

- `dist/` — preserved landing-page assets and browser-local sample demo.
- `frontend/` — React, TypeScript, Vite, Tailwind, React Flow and Three.js.
- `backend/app/` — FastAPI, organization-scoped MongoDB access, explicit migrations and Celery.
- `backend/tests/` — API, persistence and migration tests.
- `vercel.json` — static frontend build and application-route rewrites for Vercel.
- `render.yaml` — Render API and Celery worker services with a shared production environment group.
- `docs/BUILD_PROGRESS.md` — delivered layers, checks and known limitations.

The local landing demo is separate from signed-in workspaces; its browser data is never imported into an account.

## Implemented

- Preserved interactive, reduced-motion-aware landing page and sample demonstration.
- Email verification and recovery, server-side sessions, CSRF protection, rate limits and organization roles.
- Organization-isolated factory, line, machine, component and sensor registry with audit history.
- Persistent production-line editor with validation, immutable snapshots and optimistic concurrency.
- Saved-version 3D review with template geometry, synchronized selection and an accessible schematic fallback without WebGL. Material paths are illustrative, not simulated job movement.
- MongoDB collection validators and explicit, idempotent migrations.
- Separate frontend and backend deployment: Vercel static frontend; Render FastAPI API and Celery worker.

Equipment templates are descriptive only. Live machine integration, telemetry ingestion, production simulation, forecasts and validated equipment physics are not implemented yet.

## Local development

No Docker or Vercel CLI is required for local development. Configure reachable MongoDB, Redis, SMTP and S3-compatible services in a root `.env` copied from `.env.example`. MongoDB must support transactions. For local email testing, run the standalone [Mailpit binary](https://mailpit.axllent.org/docs/install/); its defaults match the example SMTP configuration.

Install dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.lock
npm --prefix frontend ci
```

In one PowerShell terminal, start FastAPI:

```powershell
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
```

In another terminal, start Vite:

```powershell
npm --prefix frontend run dev
```

Open the Vite URL (normally `http://localhost:5173`). Vite proxies `/api/v1` to the local API; `VITE_API_BASE_URL` defaults to `/api/v1`. The API readiness endpoint is `/api/v1/health/ready` and reports unavailable dependencies until they are reachable.

Run database migrations explicitly from the repository root, using the same `.env`:

```powershell
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python.exe -m app.db.migrations.runner
```

Migrations are idempotent and do not run automatically during startup or deployment.

## Separate deployment: Vercel frontend + Render backend

The browser calls the Render API directly. To keep the existing `SameSite=Strict` session and CSRF cookies reliable, use **HTTPS custom domains on the same registrable domain**, for example `app.example.com` on Vercel and `api.example.com` on Render. The default `*.vercel.app` and `*.onrender.com` addresses are different sites and are not a supported production authentication pairing.

1. **Provision external services** as described in [Required credentials and service settings](#required-credentials-and-service-settings). MongoDB must support transactions; Redis must provide a TLS `rediss://` URL.
2. **Deploy the API and worker on Render.** Create a Render Blueprint from this repository and apply [`render.yaml`](./render.yaml). It creates the FastAPI web service and Celery worker and prompts for `sync: false` values in the shared environment group. Set `PUBLIC_APP_URL` and `FRONTEND_ORIGINS` to the final HTTPS Vercel frontend origin. Attach the custom `api` domain to the web service. Keep the environment group private; do not commit populated values.
3. **Run migrations once** before serving the new API schema. In Render Shell, where the shared production environment group is available, install `requirements.lock` from the `backend` root and run `python -m app.db.migrations.runner`. If running from a secured operator machine, provide the complete production environment required by backend settings, not only MongoDB values. Serialize this step; do not run it in every web or worker startup.
4. **Deploy the frontend on Vercel.** Import the same repository with the repository root as the project root and use the checked-in [`vercel.json`](./vercel.json). Set `VITE_API_BASE_URL` to `https://api.example.com/api/v1` in the Vercel project's build environment, then assign `app.example.com` to that project. This variable is a public API address, **not a secret**.
5. Confirm the Vercel origin exactly matches `FRONTEND_ORIGINS`, open `/api/v1/health/ready` on the API, and test registration, email verification, login, logout and a protected request in a browser. Readiness is `503` until MongoDB, Redis, the S3 bucket and SMTP are all reachable.

Vercel builds only the landing page and `/app`; Render runs the Python API and Celery worker. Render, Vercel, MongoDB, Redis, mail and object storage are independently provisioned. The repository does not create accounts or provision paid services for you.

### Required credentials and service settings

These are **service credentials/settings, not a collection of AI API keys**. The implemented product does not call an LLM or other AI vendor. Do not send passwords, URIs, access keys or tokens in chat; enter them directly into your local ignored `.env` or the appropriate Vercel/Render environment-variable UI.

| Variable(s) | Needed for | How to obtain/configure |
|---|---|---|
| `MONGO_URI`, `MONGO_DATABASE` | Render API, worker and migrations | Create a MongoDB Atlas cluster with transaction support, create a least-privilege application database user, allow Render service egress in the Atlas network access list, and copy the authenticated `mongodb+srv://` URI. Set database name to `realityloop` unless choosing another consistently. |
| `REDIS_URL` | Render API, Celery worker and auth rate limits | Provision a reachable TLS Redis-compatible service and use its `rediss://` connection URL. The deployed API and worker must use the same Redis database/broker. |
| `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Render API readiness and future object storage | Create a private bucket in AWS S3 or another S3-compatible provider. Create bucket-scoped credentials with only necessary access; `HeadBucket` must succeed. |
| `S3_ENDPOINT_URL` | Render API, only for non-AWS S3-compatible storage | Copy the provider's HTTPS S3 endpoint. Leave empty for AWS S3. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER`, `SMTP_STARTTLS`, `SMTP_SSL` | Render API account verification and recovery email | Create SMTP credentials with an email provider. Obtain its host, port, username/password and verified sender address. Use STARTTLS or SSL; do not enable both. |
| `PUBLIC_APP_URL` | Render API email links | Set to the deployed HTTPS frontend origin, e.g. `https://app.example.com`. |
| `FRONTEND_ORIGINS` | Render API credentialed CORS | Set the exact comma-separated HTTPS frontend origin(s), e.g. `https://app.example.com`; no wildcard. Keep frontend and API on HTTPS subdomains of the same registrable domain for `SameSite=Strict` auth cookies. |
| `VITE_API_BASE_URL` | Vercel frontend build (public) | Set to the API URL including prefix, e.g. `https://api.example.com/api/v1`. This is not a credential and can be visible in browser assets. |
| `ENVIRONMENT=production`, `COOKIE_SECURE=true` | Render API and worker | Already set in the Render Blueprint environment group. Keep secure cookies enabled. |

Render's `sync: false` prompts are for sensitive service values and origins; populate them in Render's environment group, not in Git. For local testing, use `.env.example` as the root `.env` template. Rotate any credentials that were accidentally committed or shared.

No Vercel token, Render API key, browser API key, or separate session-signing key is needed for Git-connected deployments and the current application. Platform API tokens are only needed if you later automate deployments outside the provider's Git integration. Do not provide AI provider keys unless a future layer explicitly adds an AI-backed feature.

## Tests and verification

```powershell
npm test
npm run test:backend
npm run build:frontend
npm --prefix frontend run build:vercel
```

Backend tests use `mongomock` and transaction doubles; they do not prove live MongoDB transactions, Render connectivity, SMTP delivery, or browser cookie behavior in production. See [`docs/BUILD_PROGRESS.md`](./docs/BUILD_PROGRESS.md) for layer-specific checks and limitations.
