# Build progress

## Layer 1 — Application foundation

### Completed

- Preserved the existing landing page at `/` and added the React/TypeScript/Tailwind application at `/app`.
- Added a FastAPI service under `/api/v1`, standard JSON error responses, request IDs, liveness and dependency readiness endpoints.
- Added MongoDB organization, user and organization-membership document foundations with strict collection validators, unique indexes and an explicit, versioned migration runner.
- Added Redis, a Celery worker, MinIO with a startup bucket initializer, and a same-origin Nginx reverse proxy in Docker Compose.
- Added local environment placeholders, setup instructions, production deployment requirements and an application error boundary/API client.

### Verification

- `npm test` — passed; existing landing-page model and CSV checks.
- `npm run build:frontend` — passed; React/TypeScript production build.
- `npm audit --prefix frontend` — passed; 0 reported vulnerabilities.
- Backend pytest suite — 8 passed; health/error/request-ID, Mongo document/index persistence, and migration-runner idempotence.
- `docker compose -f infra/docker-compose.yml config --quiet` — passed with `.env.example` values.
- Local HTTP checks — landing `/`, app `/app/`, and API liveness returned 200; API readiness correctly returned 503 while MongoDB, Redis and MinIO were absent. Browser check confirmed the app renders the setup state, displays dependency status, loads its icon, and has no JavaScript exceptions or failed network connections. The expected readiness 503 was visible.
- `docker info` — unavailable: Docker Desktop's Linux engine pipe was not present. Therefore the full Compose startup and migration against a real empty MongoDB database could not be run here; the migration runner was verified with an empty in-memory test double and MongoDB-compatible persistence/index tests with `mongomock`.

### Known limitations

- Authentication, email verification, organization authorization, factory workflows and production telemetry are not implemented.
- Full Compose startup, and execution of the migration against a real empty MongoDB instance, remain unverified until Docker is available.
- The frontend is a setup-status screen, not a sign-in or dashboard mockup.
- Docker must be running to test the complete local stack; Compose config validation alone does not start containers.

### Next layer

Implement the next user-requested layer.

## Layer 2 — Authentication and organization isolation

### Completed

- Added registration with name, normalized email, password and organization name. User, organization, owner membership and the one-time verification-token digest are created in a MongoDB transaction.
- Added expiring, single-use email verification and password-reset links, generic recovery responses, login/logout, session expiration and revocation on password reset.
- Added Argon2 password hashing, server-managed opaque session cookies, CSRF double-submit protection, SameSite cookies and a production guard requiring HTTPS-secure cookies and TLS-protected SMTP.
- Added Redis-backed registration/login/recovery/verification limits that fail closed when Redis is unavailable.
- Added SMTP email delivery, a local Mailpit service, and SMTP readiness checks.
- Added roles `owner`, `administrator`, `engineer`, `operator`, `viewer`; migration `0002_authentication` upgrades earlier role names and creates strict validators/indexes for authentication tokens, sessions and factories.
- Added authenticated organization-scoped factory list/get/create routes and a persisted empty dashboard/onboarding status. Factory creation is limited to owner, administrator and engineer roles.
- Added React registration, login, verification, verification-resend, password-recovery/reset and authenticated dashboard flows. The landing page links to registration/login while preserving the separately labeled local sample demo.

### Verification

- `npm run test:backend` — 22 passed (authentication, two-organization factory isolation/guessed IDs, role enforcement, token expiry/reuse, generic recovery, logout/session revocation, protected routes, rate limits, production configuration and readiness).
- `npm run build:frontend` — passed; TypeScript check and Vite production build.
- `npm test` — passed; landing-page model, CSV and demo behavior regressions.
- `docker compose --env-file .env.example -f infra/docker-compose.yml config --quiet` — passed.
- `git diff --check` — passed.
- Browser smoke checks — registration and login screens rendered with no JavaScript errors; the landing page rendered with no failed requests and its registration, sign-in and sample-demo links pointed to the expected destinations.
- Full Docker stack and real MongoDB replica-set transaction/migration could not be exercised: `docker info` reports Docker Desktop is unable to start. Backend tests use `mongomock` and a transaction test double and therefore do not prove MongoDB server transaction behavior. SMTP delivery through a live Mailpit container remains unverified.
- `npm audit` could not reach `registry.npmjs.org` due DNS/network failure; this run does not establish a current dependency audit result.

### Known limitations

- The local account/data implementation is real, but Docker-dependent runtime behavior awaits a working Docker Desktop engine.
- No factory-line editor, sensors, machine integration, simulation or ML is included in this layer.
- Production still requires managed secret storage, a MongoDB deployment supporting transactions, trusted HTTPS ingress, and configured TLS SMTP.

### Next layer

Implement the next user-requested layer only after its scope is provided.
