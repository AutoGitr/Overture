import { isApiError } from "../rest/transport";
import { redactText, supportReference } from "./redact";

export function errorMessage(error: unknown, fallback: string): string {
  if (isApiError(error) && error.requestId) {
    return `${error.message} (Request ID: ${error.requestId})`;
  }
  if (error instanceof Error && error.message) return redactText(error.message);
  if (typeof error === "string" && error) return redactText(error);
  return fallback;
}

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

interface JobEventErrorLike {
  job?: {
    id?: string | null;
    error?: {
      message?: string | null;
    } | null;
  } | null;
}

export function jobEventErrorMessage(event: JobEventErrorLike, fallback: string): string {
  const message = errorMessage(event.job?.error?.message, fallback);
  const id = supportReference(event.job?.id);
  return id ? `${message} (Job ID: ${id})` : message;
}
