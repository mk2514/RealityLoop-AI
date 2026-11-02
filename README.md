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
- Private, organization-scoped historical sensor CSV imports with bounded preview/mapping, private S3-compatible file retention, a Redis/Celery worker, normalized readings, idempotent event keys and row-level rejection reports.
- MongoDB collection validators and explicit, idempotent migrations.
- One frontend at `/` and `/app`, deployable as a single Vercel static project. The backend remains a separate service for a later deployment step.

Equipment templates are descriptive only. Historical sensor CSV imports are available for registered sensors; live device ingestion, production simulation, forecasts and validated equipment physics are not implemented yet.

## Local development

No Docker or Vercel CLI is used. Start the unified frontend and browser-local landing demo from the repository root:

```sh
npm --prefix frontend ci
npm run dev:frontend
```

Open `http://localhost:5173`. The landing page, public sample and application routes all run through this one frontend server. The Vite proxy keeps `/api/v1` pointed at `http://127.0.0.1:8001`; backend-dependent actions show an unavailable-service message if FastAPI is not running. `VITE_API_BASE_URL` is optional and defaults to the local proxy path.

### Local integration smoke test (no containers)

The backend smoke test uses services installed or already running on the host: a MongoDB replica set, Redis-compatible broker, Mailpit SMTP sink, and local S3-compatible storage such as MinIO. The smoke runner rejects non-loopback service hosts to avoid writing test records to a remote or production environment.

1. Copy `.env.example` to `.env`. Keep the local values for MongoDB, Redis, SMTP, S3 and `PUBLIC_APP_URL`; the local MongoDB must be initialized as replica set `rs0`. The sample MongoDB URI is unauthenticated for local development only, so bind it and all other local services to loopback and never reuse it in production.
2. Start a single-node MongoDB replica set:

   ```powershell
   New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\RealityLoop\mongodb"
   mongod --dbpath "$env:LOCALAPPDATA\RealityLoop\mongodb" --replSet rs0 --bind_ip 127.0.0.1 --port 27017
   ```

   In another terminal, initialize it once and wait for a primary:

   ```powershell
   mongosh --host 127.0.0.1:27017 --eval "try { rs.status() } catch { rs.initiate({ _id: 'rs0', members: [{ _id: 0, host: '127.0.0.1:27017' }] }) }"
   mongosh --quiet --host 127.0.0.1:27017 --eval "db.hello().isWritablePrimary"
   ```

3. In separate terminals, start local Redis-compatible service on `127.0.0.1:6379` (for example, Redis in WSL or a Windows-compatible Redis service), Mailpit, and MinIO. Mailpit's standalone binary is available from its [official installation guide](https://mailpit.axllent.org/docs/install/):

   ```powershell
   # Redis terminal (or use a Windows-compatible Redis service):
   wsl --exec redis-server --bind 127.0.0.1 --port 6379
   ```

   ```powershell
   # Mailpit terminal:
   mailpit --listen 127.0.0.1:8025 --smtp 127.0.0.1:1025
   ```

   Use MinIO's standalone server binary (not a container), with root credentials matching `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` in the ignored `.env`:

   ```powershell
   New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\RealityLoop\minio"
   $env:MINIO_ROOT_USER = "realityloop-local"
   $env:MINIO_ROOT_PASSWORD = "replace-with-a-local-minio-secret"
   minio.exe server "$env:LOCALAPPDATA\RealityLoop\minio" --address 127.0.0.1:9000 --console-address 127.0.0.1:9001
   ```

   These are local-only placeholders; change the username/password in both the process environment and `.env` together. Mailpit's standalone binary is available from its [official installation guide](https://mailpit.axllent.org/docs/install/).
4. Create the local bucket once using the MinIO client (install `mc` separately):

   ```powershell
   mc alias set local http://127.0.0.1:9000 $env:S3_ACCESS_KEY_ID $env:S3_SECRET_ACCESS_KEY
   mc mb --ignore-existing local/realityloop-local
   ```

   Set those two PowerShell environment variables to the same local-only values as `.env` before running the commands:

   ```powershell
   $env:S3_ACCESS_KEY_ID = "realityloop-local"
   $env:S3_SECRET_ACCESS_KEY = "replace-with-a-local-minio-secret"
   ```

   Alternatively, create the bucket in MinIO's console at `http://127.0.0.1:9001`.
5. Install the backend and browser-test dependencies, then run the integration gate:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.lock
   npm --prefix frontend ci
   npm --prefix frontend exec -- playwright install chromium
   npm run smoke:local
   ```

The runner applies migrations twice and requires the second run to be a no-op, starts FastAPI, a solo Celery worker and Vite, checks all API readiness dependencies, submits a Celery task, then runs the browser journey. The browser test registers and verifies two independent organizations through Mailpit, rejects verification-token reuse, signs in, creates a factory/line/machine/component/sensor and valid immutable line snapshot, opens its 3D review with WebGL deliberately disabled, and asserts guessed cross-organization asset/version IDs return 404. It also verifies logout revokes the session and the protected dashboard API returns 401. The test data remains in the local MongoDB database with unique names; do not point this smoke test at shared or production services.

To run backend unit tests without those services:

```powershell
npm run test:backend
```

Migrations are idempotent and do not run automatically during startup or deployment.

### Historical sensor imports

The private import workflow is available in `/app` after selecting a sensor in
the Factory Registry. It requires the API, Redis-backed Celery worker, MongoDB
transactions, and a private S3-compatible bucket. Use the `SENSOR_IMPORT_*`
limits in `.env.example`; upload errors are shown in the UI and rejected rows
are available as an organization-authorized, short-lived signed download.
Reading normalization, event-key semantics, status behavior, limits, and
local verification are documented in
[`docs/SENSOR_IMPORTS.md`](./docs/SENSOR_IMPORTS.md).

For a local API and worker, configure the local dependencies from the setup
above, then run these from the repository root in separate PowerShell
terminals:

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
.\.venv\Scripts\python.exe -m celery -A app.worker.celery_app:celery_app worker --loglevel=INFO --pool=solo
```

The worker and API must use the same `REDIS_URL`, MongoDB database and private
storage bucket. No Docker or production deployment is part of this workflow.

### Separate staging connectivity check

This procedure is separate from the local smoke test and requires already-provisioned staging services; it does not deploy or provision anything.

1. Use HTTPS custom domains on the same registrable domain, such as `app.example.com` (Vercel) and `api.example.com` (Render). The default `*.vercel.app` and `*.onrender.com` domains are cross-site and are not supported for the current `SameSite=Strict` session flow.
2. Set Render `FRONTEND_ORIGINS=https://app.example.com`, `PUBLIC_APP_URL=https://app.example.com`, and `COOKIE_SECURE=true`; set Vercel's build-time `VITE_API_BASE_URL=https://api.example.com/api/v1` and rebuild.
3. In browser devtools, verify the API's credentialed CORS response allows only the exact frontend origin, includes `Access-Control-Allow-Credentials: true`, and permits `X-CSRF-Token`. Verify login issues an HttpOnly, Secure, SameSite=Strict session cookie; browser requests with credentials can reach the protected dashboard; and a mutation without the CSRF token is rejected. Do not expect browser JavaScript to read the session cookie.
4. Register a second staging organization and confirm guessed IDs from the first organization receive denial. Do not use real production accounts or telemetry for this check.

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
