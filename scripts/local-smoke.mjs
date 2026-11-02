import { existsSync, readFileSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { delimiter, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const frontend = resolve(root, "frontend");
const envPath = resolve(root, ".env");
const localPython = resolve(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const pythonCommand = existsSync(localPython)
  ? localPython
  : process.platform === "win32"
    ? "py"
    : "python3";
const pythonPrefix = pythonCommand === "py" ? ["-3"] : [];
const children = [];
let stopping = false;

function readLocalEnvironment() {
  if (!existsSync(envPath)) {
    throw new Error("Missing root .env. Copy .env.example to .env and configure local services.");
  }
  const values = new Map();
  for (const line of readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match) continue;
    const value = match[2].replace(/^(['"])(.*)\1$/, "$2");
    values.set(match[1], value);
  }
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined) values.set(key, value);
  }
  return values;
}

function requireLoopback(host, label) {
  const normalizedHost = host.toLowerCase().replace(/^\[|\]$/g, "");
  if (!["localhost", "127.0.0.1", "::1"].includes(normalizedHost)) {
    throw new Error(`${label} must use a loopback host for this local-only smoke test.`);
  }
}

function mongoHosts(uri) {
  const separator = uri.indexOf("://");
  if (separator < 0 || !/^mongodb(?:\+srv)?:$/i.test(uri.slice(0, separator + 1))) {
    throw new Error("MONGO_URI must use the mongodb:// or mongodb+srv:// scheme.");
  }
  const authority = uri.slice(separator + 3).split(/[/?#]/, 1)[0];
  if (!authority) throw new Error("MONGO_URI must contain at least one MongoDB host.");
  const servers = authority.slice(authority.lastIndexOf("@") + 1).split(",");
  return servers.map((server) => {
    const host = new URL(`mongodb://${server}`).hostname;
    if (!host) throw new Error("MONGO_URI contains an invalid MongoDB host.");
    return host;
  });
}

function validateLocalTargets(values) {
  const mongoUri = values.get("MONGO_URI") ?? "";
  const mongoServers = mongoUri
    ? mongoHosts(mongoUri)
    : [values.get("MONGO_HOST") ?? "localhost"];
  if (!mongoServers.length || mongoServers.some((host) => !host)) {
    throw new Error("MONGO_URI must contain at least one valid MongoDB host.");
  }
  for (const host of mongoServers) requireLoopback(host, "MongoDB");

  const redis = new URL(values.get("REDIS_URL") ?? "redis://localhost:6379/0");
  requireLoopback(redis.hostname, "Redis");

  const smtpHost = values.get("SMTP_HOST") ?? "localhost";
  requireLoopback(smtpHost, "SMTP");

  const storageEndpoint = values.get("S3_ENDPOINT_URL");
  if (!storageEndpoint) {
    throw new Error("S3_ENDPOINT_URL must point to local S3-compatible storage.");
  }
  requireLoopback(new URL(storageEndpoint).hostname, "Object storage");

  const appUrl = new URL(values.get("PUBLIC_APP_URL") ?? "http://127.0.0.1:5173");
  requireLoopback(appUrl.hostname, "PUBLIC_APP_URL");
  if (appUrl.origin !== "http://127.0.0.1:5173") {
    throw new Error("PUBLIC_APP_URL must be http://127.0.0.1:5173 so verification links use the smoke-test origin.");
  }
}

function pythonArgs(args) {
  return [...pythonPrefix, ...args];
}

function backendEnvironment() {
  const backendPath = resolve(root, "backend");
  return {
    ...process.env,
    PYTHONPATH: [backendPath, process.env.PYTHONPATH].filter(Boolean).join(delimiter),
  };
}

function run(command, args, label, options = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    env: backendEnvironment(),
    encoding: "utf8",
    stdio: "pipe",
    ...options,
  });
  const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
  if (output) process.stdout.write(output);
  if (result.error) throw new Error(`${label} could not start: ${result.error.message}`);
  if (result.status !== 0) throw new Error(`${label} exited with status ${result.status ?? "unknown"}.`);
  return output;
}

function start(command, args, label, options = {}) {
  const child = spawn(command, args, {
    cwd: root,
    env: backendEnvironment(),
    stdio: "inherit",
    windowsHide: true,
    ...options,
  });
  children.push({ child, label });
  child.on("error", (error) => {
    if (!stopping) {
      console.error(`${label} failed to start: ${error.message}`);
      process.exitCode = 1;
      stopChildren();
    }
  });
  child.on("exit", (code, signal) => {
    if (!stopping && code !== 0) {
      console.error(`${label} exited unexpectedly (${signal ?? code ?? "unknown"}).`);
      process.exitCode = 1;
      stopChildren();
    }
  });
  return child;
}

function stopChildren() {
  if (stopping) return;
  stopping = true;
  for (const { child } of [...children].reverse()) {
    if (child.exitCode === null && child.signalCode === null) child.kill();
  }
}

async function waitFor(url, label, readyStatus = 200, timeoutMs = 75_000) {
  const deadline = Date.now() + timeoutMs;
  let lastResult = "no response";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1500) });
      const body = await response.text();
      lastResult = `${response.status}: ${body.slice(0, 500)}`;
      if (response.status === readyStatus) return body;
    } catch (error) {
      lastResult = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 1000));
  }
  throw new Error(`${label} did not become ready. Last response: ${lastResult}`);
}

async function main() {
  const values = readLocalEnvironment();
  validateLocalTargets(values);

  const migrations = ["-m", "app.db.migrations.runner"];
  run(pythonCommand, pythonArgs(migrations), "First migration run");
  const secondMigrationRun = run(pythonCommand, pythonArgs(migrations), "Second migration run");
  if (!secondMigrationRun.includes("MongoDB schema is up to date.")) {
    throw new Error("The second migration run did not report an idempotent no-op.");
  }

  const api = start(
    pythonCommand,
    pythonArgs(["-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8001"]),
    "FastAPI",
  );
  const worker = start(
    pythonCommand,
    pythonArgs(["-m", "celery", "-A", "app.worker.celery_app:celery_app", "worker", "--pool=solo", "--loglevel=INFO"]),
    "Celery worker",
  );
  const vite = start(
    process.execPath,
    [resolve(frontend, "node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
    "Vite",
    { env: { ...backendEnvironment(), VITE_API_BASE_URL: "/api/v1" } },
  );

  await waitFor("http://127.0.0.1:8001/api/v1/health/ready", "Backend service dependencies");
  await waitFor("http://127.0.0.1:5173/", "Frontend");

  run(
    pythonCommand,
    pythonArgs([
      "-c",
      "from app.worker.celery_app import healthcheck; result = healthcheck.delay(); value = result.get(timeout=30); assert value == 'ok', value; print('Celery round trip: ok')",
    ]),
    "Celery broker-to-worker round trip",
  );

  const playwrightCli = resolve(frontend, "node_modules/@playwright/test/cli.js");
  if (!existsSync(playwrightCli)) {
    throw new Error("Playwright is missing. Run npm --prefix frontend ci, then install Chromium with npm --prefix frontend exec -- playwright install chromium.");
  }
  const smokeResult = spawnSync(
    process.execPath,
    [playwrightCli, "test", "--config", "playwright.smoke.config.ts"],
    {
      cwd: frontend,
      env: {
        ...process.env,
        LOCAL_SMOKE_BASE_URL: "http://127.0.0.1:5173",
        MAILPIT_API_URL: "http://127.0.0.1:8025/api/v1",
      },
      stdio: "inherit",
    },
  );
  if (smokeResult.error) throw new Error(`Playwright could not start: ${smokeResult.error.message}`);
  if (smokeResult.status !== 0) throw new Error(`Browser smoke test exited with status ${smokeResult.status ?? "unknown"}.`);
  console.log("Local integration smoke passed.");

  for (const processRef of [api, worker, vite]) {
    if (processRef.exitCode !== null || processRef.signalCode !== null) {
      throw new Error("A local service exited before the smoke test completed.");
    }
  }
}

process.on("SIGINT", () => {
  stopChildren();
  process.exitCode = 130;
});
process.on("SIGTERM", () => {
  stopChildren();
  process.exitCode = 143;
});

main()
  .catch((error) => {
    console.error(`Local integration smoke failed: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  })
  .finally(stopChildren);
