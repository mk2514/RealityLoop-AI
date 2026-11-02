export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    request_id?: string;
  };
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

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
    credentials: "same-origin",
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
  const response = await fetch("/api/v1/health/ready", {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
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
