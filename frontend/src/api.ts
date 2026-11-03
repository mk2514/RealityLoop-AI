export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    request_id?: string;
  };
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(/\/+$/, "");
const API_CONFIGURED = API_BASE_URL === "/api/v1" || Boolean(import.meta.env.VITE_API_BASE_URL) || import.meta.env.DEV;

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly requestId?: string,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function requireBackendConfiguration(): void {
  if (!API_CONFIGURED) {
    throw new ApiError(
      "The backend service is not connected to this frontend yet. Registration, sign-in, and workspace actions will be available after the backend is deployed.",
      503,
      undefined,
      "service_unavailable",
    );
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  requireBackendConfiguration();
  const method = (init?.method ?? "GET").toUpperCase();
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  if (init?.body && !headers.has("Content-Type") && !isFormData) {
    headers.set("Content-Type", "application/json");
  }
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    headers.set("X-CSRF-Token", await getCsrfToken());
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    method,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    let body: ApiErrorBody = {};
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = {};
    }

    throw new ApiError(
      body.error?.message ?? "The service could not complete this request.",
      response.status,
      body.error?.request_id ?? response.headers.get("X-Request-ID") ?? undefined,
      body.error?.code,
    );
  }

  return (await response.json()) as T;
}

async function getCsrfToken(): Promise<string> {
  const cookieToken = document.cookie
    .split("; ")
    .find((cookie) => cookie.startsWith("rl_csrf="))
    ?.slice("rl_csrf=".length);
  if (cookieToken) return decodeURIComponent(cookieToken);

  const response = await fetch(`${API_BASE_URL}/csrf`, {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("A security token could not be issued.", response.status);
  }
  if (!response.ok || typeof body !== "object" || body === null) {
    throw toApiError(response, body);
  }
  const token = (body as { csrf_token?: unknown }).csrf_token;
  if (typeof token !== "string" || token.length === 0) {
    throw new ApiError("A security token could not be issued.", response.status);
  }
  return token;
}

export interface ReadinessResponse {
  status: "ready" | "not_ready";
  dependencies: Record<string, "ready" | "unavailable">;
  request_id: string;
}

function isReadinessResponse(value: unknown): value is ReadinessResponse {
  if (typeof value !== "object" || value === null) return false;
  const data = value as Record<string, unknown>;
  if (
    (data.status !== "ready" && data.status !== "not_ready") ||
    typeof data.request_id !== "string" ||
    typeof data.dependencies !== "object" ||
    data.dependencies === null
  ) {
    return false;
  }
  return Object.values(data.dependencies).every(
    (status) => status === "ready" || status === "unavailable",
  );
}

function toApiError(response: Response, body: unknown): ApiError {
  const data =
    typeof body === "object" && body !== null ? (body as ApiErrorBody) : {};
  const error = data.error;
  return new ApiError(
    error?.message ?? "The service could not complete this request.",
    response.status,
    error?.request_id ?? response.headers.get("X-Request-ID") ?? undefined,
    error?.code,
  );
}

export async function getReadiness(): Promise<ReadinessResponse> {
  requireBackendConfiguration();
  const response = await fetch(`${API_BASE_URL}/health/ready`, {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    if (!response.ok) throw toApiError(response, body);
    throw new ApiError("The readiness service returned an invalid response.", response.status);
  }
  if (isReadinessResponse(body) && (response.ok || response.status === 503)) return body;
  if (!response.ok) throw toApiError(response, body);
  throw new ApiError("The readiness service returned an invalid response.", response.status);
}
