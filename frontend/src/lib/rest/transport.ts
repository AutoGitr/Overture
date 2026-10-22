import type { CreateClientConfig } from "../../generated/rest/client.gen";
import { CSRF_COOKIE, CSRF_HEADER, MUTATING_METHODS } from "../../generated/settings";
import { redactText, supportReference } from "../utils/redact";

const MUTATING = new Set<string>(MUTATING_METHODS);
let sessionController = new AbortController();
let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export function reportUnauthorized(): void {
  unauthorizedHandler?.();
}

/** Cancel work from the previous session before any new session can use its results. */
export function resetTransportSession(): void {
  sessionController.abort();
  sessionController = new AbortController();
}

export class ApiError extends Error {
  readonly status: number;
  readonly requestId: string | null;

  constructor(message: string, status: number, requestId: string | null = null) {
    super(redactText(message));
    this.name = "ApiError";
    this.status = status;
    this.requestId = supportReference(requestId);
  }

  get retryable(): boolean {
    return this.status === 0 || this.status >= 500;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

function cookieValue(name: string): string {
  const prefix = `${name}=`;
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (!cookie) return "";
  try {
    return decodeURIComponent(cookie.slice(prefix.length));
  } catch {
    return cookie.slice(prefix.length);
  }
}

function validationDetailToMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return "";

  return detail
    .map((entry) => {
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) return "";
      const record = entry as Record<string, unknown>;
      const msg = record.msg;
      const loc = record.loc;
      const path = Array.isArray(loc)
        ? loc.filter((part) => typeof part === "string" || typeof part === "number").join(".")
        : "";
      if (typeof msg !== "string") return "";
      return path ? `${path}: ${msg}` : msg;
    })
    .filter(Boolean)
    .join("; ");
}

function responseErrorMessage(payload: unknown, status: number): string {
  const fallback =
    status >= 500
      ? "Overture is unavailable. Please try again."
      : `Request failed (HTTP ${status}).`;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  return validationDetailToMessage(detail) || fallback;
}

export async function overtureFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  new Headers(init.headers).forEach((value, key) => headers.set(key, value));
  const method = (init.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  const signal = AbortSignal.any([
    sessionController.signal,
    ...(input instanceof Request ? [input.signal] : []),
    ...(init.signal ? [init.signal] : []),
  ]);
  signal.throwIfAborted();

  if (MUTATING.has(method)) {
    const csrf = cookieValue(CSRF_COOKIE);
    if (csrf) headers.set(CSRF_HEADER, csrf);
  }

  let response: Response;
  try {
    response = await globalThis.fetch(input, {
      ...init,
      credentials: "include",
      headers,
      signal,
    });
    signal.throwIfAborted();
  } catch (error) {
    if (signal.aborted) throw signal.reason;
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError("Could not reach Overture. Check your connection and try again.", 0);
  }

  const requestId = response.headers.get("X-Request-ID");
  if (response.status === 401) {
    const url = new URL(input instanceof Request ? input.url : String(input), location.origin);
    if (url.pathname !== "/api/auth/login") reportUnauthorized();
    throw new ApiError("Your session has expired. Please sign in again.", 401, requestId);
  }
  if (!response.ok) {
    const payload = await response
      .clone()
      .json()
      .catch(() => null);
    signal.throwIfAborted();
    throw new ApiError(responseErrorMessage(payload, response.status), response.status, requestId);
  }
  return response;
}

export const createClientConfig: CreateClientConfig = (config) => ({
  ...config,
  baseUrl: config?.baseUrl || (typeof location === "undefined" ? "" : location.origin),
  fetch: overtureFetch,
});
