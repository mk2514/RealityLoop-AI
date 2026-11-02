import { randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

const baseUrl = process.env.LOCAL_SMOKE_BASE_URL ?? "http://127.0.0.1:5173";
const mailpitApi = process.env.MAILPIT_API_URL ?? "http://127.0.0.1:8025/api/v1";
const password = `Smoke-${randomUUID()}-local!`;

type MailpitMessage = {
  ID: string;
  To: { Address: string }[];
};

type ApiResult = {
  status: number;
  body: unknown;
};

async function verificationLink(email: string): Promise<string> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const listResponse = await fetch(`${mailpitApi}/messages?limit=100`);
    if (!listResponse.ok) {
      throw new Error(`Mailpit message listing failed with HTTP ${listResponse.status}.`);
    }
    const result = await listResponse.json() as { messages?: MailpitMessage[] };
    const message = (result.messages ?? []).find((candidate) =>
      candidate.To.some((recipient) => recipient.Address.toLowerCase() === email.toLowerCase()),
    );
    if (message) {
      const detailResponse = await fetch(`${mailpitApi}/message/${encodeURIComponent(message.ID)}`);
      if (!detailResponse.ok) {
        throw new Error(`Mailpit message retrieval failed with HTTP ${detailResponse.status}.`);
      }
      const detail = await detailResponse.json() as Record<string, unknown>;
      const content = Object.values(detail).filter((value) => typeof value === "string").join("\n");
      const match = content.match(/https?:\/\/[^\s<>"']+\/app\/verify\?token=[A-Za-z0-9._~%-]+/);
      if (match) return match[0];
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 500));
  }
  throw new Error(`No verification email containing a link arrived for ${email}.`);
}

async function registerVerifyAndSignIn(
  page: Page,
  email: string,
  organization: string,
) {
  await page.goto("/app/register");
  await page.getByLabel("Full name").fill("Local Smoke Engineer");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Organization name").fill(organization);
  await page.getByLabel(/Password/).fill(password);
  await page.getByRole("button", { name: "CREATE ACCOUNT" }).click();
  await expect(page.getByText(/If registration can be completed/)).toBeVisible();

  const link = await verificationLink(email);
  const verificationToken = new URL(link).searchParams.get("token");
  if (!verificationToken) throw new Error("The verification email link did not contain its one-time token.");
  await page.goto(link);
  await page.getByRole("button", { name: "VERIFY EMAIL" }).click();
  await expect(page.getByText("Email verified. Sign in to open your workspace.")).toBeVisible();
  const replay = await apiRequest(page, "POST", "/auth/verify", { token: verificationToken });
  expect(replay.status, "A verified email token must be single-use.").toBe(400);
  await page.getByRole("link", { name: "Continue to sign in" }).click();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "SIGN IN" }).click();
  await expect(page).toHaveURL(/\/app\/dashboard$/);
  await expect(page.getByRole("heading", { name: organization })).toBeVisible();
}

async function apiRequest(
  page: Page,
  method: string,
  path: string,
  payload?: Record<string, unknown>,
): Promise<ApiResult> {
  return page.evaluate(async ({ method, path, payload }) => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (payload) {
      const csrfResponse = await fetch("/api/v1/csrf", { credentials: "include" });
      if (!csrfResponse.ok) throw new Error(`CSRF token request failed: ${csrfResponse.status}`);
      const csrf = await csrfResponse.json() as { csrf_token: string };
      headers["Content-Type"] = "application/json";
      headers["X-CSRF-Token"] = csrf.csrf_token;
    }
    const response = await fetch(`/api/v1${path}`, {
      method,
      credentials: "include",
      headers,
      body: payload ? JSON.stringify(payload) : undefined,
    });
    const body = response.headers.get("content-type")?.includes("application/json")
      ? await response.json()
      : await response.text();
    return { status: response.status, body };
  }, { method, path, payload });
}

function createdId(result: ApiResult, resource: string): string {
  if (result.status !== 201 || typeof result.body !== "object" || result.body === null || !("id" in result.body)) {
    throw new Error(`${resource} creation failed: HTTP ${result.status} ${JSON.stringify(result.body)}`);
  }
  return String(result.body.id);
}

test("registered organizations can build and review a saved line without cross-org access", async ({ browser, page }) => {
  await page.addInitScript(() => {
    const nativeGetContext = HTMLCanvasElement.prototype.getContext;
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
      configurable: true,
      value: new Proxy(nativeGetContext, {
        apply(target, thisArg, args: [string, ...unknown[]]) {
          if (args[0] === "webgl" || args[0] === "webgl2" || args[0] === "experimental-webgl") {
            return null;
          }
          return Reflect.apply(target, thisArg, args);
        },
      }),
    });
  });
  const unique = randomUUID();
  const firstEmail = `smoke-owner-${unique}@example.com`;
  const firstOrganization = `Smoke Factory Group ${unique}`;
  await registerVerifyAndSignIn(page, firstEmail, firstOrganization);

  const factoryId = createdId(await apiRequest(page, "POST", "/factories", {
    name: `Smoke Factory ${unique}`,
    timezone: "UTC",
    description: "Local integration smoke data.",
    unit_preferences: { system: "metric", temperature: "C" },
    operating_calendar: { shifts: [] },
  }), "Factory");
  const lineId = createdId(await apiRequest(page, "POST", `/factories/${factoryId}/lines`, {
    name: `Smoke Line ${unique}`,
    description: "",
  }), "Production line");
  const machineId = createdId(await apiRequest(page, "POST", `/lines/${lineId}/machines`, {
    identity: `SMOKE-CNC-${unique}`,
    name: "Smoke CNC",
    machine_type: "cnc_cutting",
    capabilities: ["cut_material"],
    nominal_cycle_time_seconds: 54,
    capacity_per_hour: 60,
    operating_state: "offline",
  }), "Machine");
  const componentId = createdId(await apiRequest(page, "POST", `/machines/${machineId}/components`, {
    identity: `SMOKE-MOTOR-${unique}`,
    name: "Smoke motor",
    component_type: "motor",
  }), "Component");
  const sensor = await apiRequest(page, "POST", `/components/${componentId}/sensors`, {
    identity: `SMOKE-TEMP-${unique}`,
    name: "Smoke temperature sensor",
    measurement_type: "temperature",
    unit: "C",
    expected_reporting_interval_seconds: 10,
    thresholds: {},
    calibration: {},
  });
  if (sensor.status !== 201) {
    throw new Error(`Sensor creation failed: HTTP ${sensor.status} ${JSON.stringify(sensor.body)}`);
  }

  const model = {
    schema_version: 1,
    layout: {
      nodes: [
        { id: "source", type: "source", label: "Raw stock", position: { x: 0, y: 0 } },
        { id: "cnc", type: "machine", machine_id: machineId, label: "CNC Cutting", position: { x: 160, y: 0 } },
        { id: "sink", type: "sink", label: "Finished goods", position: { x: 320, y: 0 } },
      ],
      edges: [
        { id: "source-to-cnc", source: "source", target: "cnc", source_handle: "out", target_handle: "in" },
        { id: "cnc-to-sink", source: "cnc", target: "sink", source_handle: "out", target_handle: "in" },
      ],
      transfer_settings: { use_layout_distance: false, pixels_per_meter: 100, default_speed_meters_per_second: 1 },
    },
    products: [{ id: "product-1", name: "Smoke bracket", sku: "SMOKE-1" }],
    recipes: [{
      id: "recipe-1",
      product_id: "product-1",
      steps: [{
        id: "cut-step",
        operation: "cut_material",
        machine_node_ids: ["cnc"],
        cycle_time_seconds: 54,
        setup_time_seconds: 0,
        changeover_time_seconds: 0,
        batch_size: 1,
        operator_count: 1,
        resources: [],
      }],
    }],
  };
  const saved = await apiRequest(page, "PUT", `/lines/${lineId}/model`, {
    expected_revision: 0,
    model,
  });
  if (
    saved.status !== 200
    || typeof saved.body !== "object"
    || saved.body === null
    || !("validation" in saved.body)
    || typeof saved.body.validation !== "object"
    || saved.body.validation === null
    || !("valid" in saved.body.validation)
    || saved.body.validation.valid !== true
  ) {
    throw new Error(`Line snapshot save/validation failed: HTTP ${saved.status} ${JSON.stringify(saved.body)}`);
  }

  await page.reload();
  await expect(page.getByRole("button", { name: "OPEN 2D LINE EDITOR" })).toBeVisible();
  await page.getByRole("button", { name: "OPEN 2D LINE EDITOR" }).click();
  await expect(page.getByRole("heading", { name: "2D line editor" })).toBeVisible();
  await page.getByRole("button", { name: "3D REVIEW" }).click();
  await expect(page.getByText("IMMUTABLE SNAPSHOT V1. Draft edits appear here only after saving a new version.")).toBeVisible();
  await expect(page.locator('svg[aria-label="Static schematic of the saved line; WebGL is unavailable"]')).toBeVisible();
  await page.getByRole("button", { name: "Select CNC Cutting" }).click();
  const inspector = page.getByRole("complementary", { name: "Machine and component inspector" });
  await expect(inspector.getByRole("heading", { name: "CNC Cutting" })).toBeVisible();
  await expect(inspector.getByText("Stored asset metadata only; this view contains no live telemetry.")).toBeVisible();
  await expect(inspector.getByRole("button", { name: /Smoke motor/ })).toBeVisible();

  const secondContext = await browser.newContext({ baseURL: baseUrl });
  try {
    const secondPage = await secondContext.newPage();
    const secondEmail = `smoke-owner-two-${unique}@example.com`;
    await registerVerifyAndSignIn(secondPage, secondEmail, `Separate Smoke Org ${unique}`);
    for (const path of [
      `/factories/${factoryId}`,
      `/machines/${machineId}`,
      `/lines/${lineId}/versions/1`,
    ]) {
      const denied = await apiRequest(secondPage, "GET", path);
      expect(denied.status, `Second organization unexpectedly accessed ${path}`).toBe(404);
    }
  } finally {
    await secondContext.close();
  }

  await page.getByText("ACCOUNT / OWNER", { exact: true }).click();
  await page.getByRole("button", { name: "SIGN OUT" }).click();
  await expect(page).toHaveURL(/\/app\/login$/);
  const revokedSessionRequest = await apiRequest(page, "GET", "/dashboard");
  expect(revokedSessionRequest.status, "A signed-out session must not access the dashboard API.").toBe(401);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("link", { name: /get started/i })).toBeVisible();
  await page.getByRole("link", { name: /get started/i }).click();
  await expect(page).toHaveURL(/\/app\/register$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
});
