const API_BASE = "";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly code: string | null;
  readonly params: Record<string, unknown>;

  constructor(
    status: number,
    detail: string,
    code: string | null = null,
    params: Record<string, unknown> = {},
  ) {
    super(`API error ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.params = params;
  }
}

export type ApiErrorPayload = {
  detail: string;
  code: string | null;
  params: Record<string, unknown>;
};

export function apiErrorPayload(text: string): ApiErrorPayload {
  try {
    const payload: unknown = JSON.parse(text);
    if (typeof payload === "object" && payload !== null) {
      const record = payload as Record<string, unknown>;
      const detail = typeof record.detail === "string" ? record.detail : "Request failed";
      const error =
        typeof record.error === "object" && record.error !== null
          ? (record.error as Record<string, unknown>)
          : null;
      const code = typeof error?.code === "string" && error.code ? error.code : null;
      const params =
        typeof error?.params === "object" && error.params !== null && !Array.isArray(error.params)
          ? (error.params as Record<string, unknown>)
          : {};
      return { detail, code, params };
    }
  } catch {
    // Never expose arbitrary non-JSON response bodies to the UI.
  }
  return { detail: "Request failed", code: null, params: {} };
}

export async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const error = apiErrorPayload(await response.text());
    throw new ApiError(response.status, error.detail, error.code, error.params);
  }
  return response.json() as Promise<T>;
}

export async function fetchStream(
  path: string,
  options?: RequestInit,
): Promise<ReadableStream<Uint8Array>> {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok || !response.body) {
    const error = apiErrorPayload(await response.text());
    throw new ApiError(response.status, error.detail, error.code, error.params);
  }
  return response.body;
}
