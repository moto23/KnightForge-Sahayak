/**
 * Central API client — the ONLY place fetch/XHR is called (Phase 9B).
 *
 * Everything above this (feature services, hooks, pages) works with typed
 * functions and a single error shape: ApiError. The backend's uniform error
 * envelope {"error": {"code", "message"}} is parsed here once, never in pages.
 *
 * Production behaviours:
 *  - environment-based base URL (NEXT_PUBLIC_API_BASE_URL)
 *  - per-request timeout (default 20s) via AbortController
 *  - automatic retry for SAFE requests only (GET) on network errors / 5xx
 *  - caller cancellation via an optional AbortSignal (aborts are NOT retried)
 *  - FastAPI 422 validation bodies ({"detail": [...]}) flattened to a message
 */

import type { ApiErrorEnvelope } from "@/types/api";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** Default per-request timeout (ms). */
const REQUEST_TIMEOUT_MS = 20_000;
/** GET requests are retried this many extra times on network errors / 5xx. */
const SAFE_RETRIES = 2;
/** Backoff between retries (ms), multiplied by the attempt number. */
const RETRY_BACKOFF_MS = 400;

/** One error type for the whole frontend — status + stable backend code. */
export class ApiError extends Error {
  /** HTTP status; 0 means the network request itself failed. */
  readonly status: number;
  /** Backend machine code (e.g. "interview_incomplete") or a client code. */
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  /** True when the backend is unreachable (server down, CORS, offline). */
  get isNetworkError(): boolean {
    return this.status === 0 && this.code !== "cancelled";
  }

  /** True when the request timed out client-side. */
  get isTimeout(): boolean {
    return this.code === "timeout";
  }

  /** True when the caller aborted the request (never surfaced to users). */
  get isCancelled(): boolean {
    return this.code === "cancelled";
  }
}

/** Narrow an unknown catch into ApiError (network failures become status 0). */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof DOMException && error.name === "AbortError") {
    return new ApiError(0, "cancelled", "Request was cancelled.");
  }
  return new ApiError(
    0,
    "network_error",
    "Cannot reach the Sahayak backend. Is the server running on " +
      `${API_BASE_URL}?`,
  );
}

/** FastAPI request-validation item ({"detail": [{loc, msg, ...}]}). */
type FastApiValidationItem = { loc?: (string | number)[]; msg?: string };

async function parseError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let message = `Request failed with status ${response.status}.`;
  try {
    const body = (await response.json()) as
      | ApiErrorEnvelope
      | { detail?: string | FastApiValidationItem[] };
    if ("error" in body && body.error) {
      code = body.error.code;
      message = body.error.message;
    } else if ("detail" in body && typeof body.detail === "string") {
      message = body.detail;
    } else if ("detail" in body && Array.isArray(body.detail)) {
      // FastAPI 422 — flatten field validation errors into one readable line.
      code = "validation_error";
      message = body.detail
        .map((item) => {
          const field = item.loc?.slice(1).join(".") || "request";
          return `${field}: ${item.msg ?? "invalid value"}`;
        })
        .join("; ");
    }
  } catch {
    /* non-JSON error body — keep the generic message */
  }
  return new ApiError(response.status, code, message);
}

export type RequestOptions = {
  /** Caller-side cancellation (component unmount, superseded request). */
  signal?: AbortSignal;
  /** Override the default 20s timeout. */
  timeoutMs?: number;
  /** Cookie behavior — "include" is required by /auth endpoints (Phase 12). */
  credentials?: RequestCredentials;
};

/* --------------------------------------------------------------------- *
 * Access token (Phase 12) — held in MEMORY only, never storage/cookies.
 * The auth context sets it after login/refresh; every request carries it
 * as an Authorization header. Guests simply have none.
 * --------------------------------------------------------------------- */

let accessToken: string | null = null;

/** Set (or clear with null) the bearer token attached to every request. */
export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** True when a signed-in access token is currently held. */
export function hasAccessToken(): boolean {
  return accessToken !== null;
}

/**
 * Typed JSON request with timeout + safe-method retry.
 * Throws ApiError on any failure.
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  options: RequestOptions = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const attempts = method === "GET" ? 1 + SAFE_RETRIES : 1;
  let lastError: ApiError = new ApiError(0, "network_error", "Request failed.");

  for (let attempt = 0; attempt < attempts; attempt++) {
    // Compose: caller cancellation + per-attempt timeout.
    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(new DOMException("timeout", "AbortError")),
      options.timeoutMs ?? REQUEST_TIMEOUT_MS,
    );
    const onCallerAbort = () => controller.abort();
    options.signal?.addEventListener("abort", onCallerAbort, { once: true });

    try {
      const response = await fetch(`${API_BASE_URL}${path}`, {
        ...init,
        headers: {
          ...(init.body ? { "Content-Type": "application/json" } : {}),
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
          ...init.headers,
        },
        credentials: options.credentials,
        signal: controller.signal,
      });
      if (!response.ok) {
        const apiError = await parseError(response);
        // Retry GETs on 5xx; 4xx are deterministic — fail immediately.
        if (method === "GET" && apiError.status >= 500 && attempt < attempts - 1) {
          lastError = apiError;
          await new Promise((r) => setTimeout(r, RETRY_BACKOFF_MS * (attempt + 1)));
          continue;
        }
        throw apiError;
      }
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      // Distinguish caller cancellation from timeout from network failure.
      if (options.signal?.aborted) {
        throw new ApiError(0, "cancelled", "Request was cancelled.");
      }
      const isAbort =
        error instanceof DOMException && error.name === "AbortError";
      lastError = isAbort
        ? new ApiError(
            0,
            "timeout",
            "The backend took too long to respond. Please try again.",
          )
        : toApiError(error);
      // Network errors / timeouts on GETs are retried; mutations are not.
      if (method === "GET" && attempt < attempts - 1) {
        await new Promise((r) => setTimeout(r, RETRY_BACKOFF_MS * (attempt + 1)));
        continue;
      }
      throw lastError;
    } finally {
      clearTimeout(timeout);
      options.signal?.removeEventListener("abort", onCallerAbort);
    }
  }
  throw lastError;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, {}, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(
      path,
      {
        method: "POST",
        body: body === undefined ? undefined : JSON.stringify(body),
      },
      options,
    ),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(
      path,
      {
        method: "PATCH",
        body: body === undefined ? undefined : JSON.stringify(body),
      },
      options,
    ),
  delete: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { method: "DELETE" }, options),
};

/**
 * Multipart upload with real progress callbacks (fetch cannot report upload
 * progress, so this one function uses XHR). Resolves to the parsed JSON body.
 * Supports cancellation via `signal`; uploads are never auto-retried.
 */
export function apiUpload<T>(
  path: string,
  file: File,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal,
  extraFields?: Record<string, string>,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}${path}`);
    xhr.responseType = "json";
    xhr.timeout = 120_000; // large files on slow links — generous but bounded
    if (accessToken) {
      // Signed-in uploads carry the token so history lands on the account.
      xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`);
    }

    signal?.addEventListener("abort", () => xhr.abort(), { once: true });

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as T);
      } else {
        const body = xhr.response as ApiErrorEnvelope | null;
        reject(
          new ApiError(
            xhr.status,
            body?.error?.code ?? `http_${xhr.status}`,
            body?.error?.message ?? `Upload failed with status ${xhr.status}.`,
          ),
        );
      }
    };
    xhr.onerror = () =>
      reject(
        new ApiError(0, "network_error", "Upload failed — backend unreachable."),
      );
    xhr.ontimeout = () =>
      reject(new ApiError(0, "timeout", "Upload timed out. Please try again."));
    xhr.onabort = () =>
      reject(new ApiError(0, "cancelled", "Upload was cancelled."));

    const form = new FormData();
    form.append("file", file);
    for (const [name, value] of Object.entries(extraFields ?? {})) {
      form.append(name, value);
    }
    xhr.send(form);
  });
}

/** Absolute URL helper for browser-native navigation (PDF downloads). */
export function absoluteUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

/**
 * Fetch a protected file and return an object URL for it.
 *
 * File endpoints are ownership-checked from the Bearer token, and a browser
 * CANNOT attach that token to `<img src>`, an `<iframe>`, or a plain download
 * link — those go out anonymously, so every file belonging to a signed-in user
 * came back 404 and rendered as a broken thumbnail. Fetching the bytes here,
 * through the same authenticated path as every other call, and handing the
 * caller a `blob:` URL keeps the server check exactly as strict while letting
 * the browser display the result.
 *
 * The caller owns the returned URL and must `URL.revokeObjectURL` it.
 */
export async function fetchBlobUrl(
  path: string,
  signal?: AbortSignal,
): Promise<string> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    signal,
  });
  if (!response.ok) throw await parseError(response);
  return URL.createObjectURL(await response.blob());
}

/** Fetch a protected file and save it under `filename`. */
export async function downloadProtectedFile(
  path: string,
  filename: string,
): Promise<void> {
  const url = await fetchBlobUrl(path);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    // Revoked on the next tick: revoking synchronously can cancel the download
    // in some browsers before it has read the blob.
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }
}
