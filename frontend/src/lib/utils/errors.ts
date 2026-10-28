import { redactText } from "./redact";

/**
 * A message for the person using Overture. Request and job IDs stay in the
 * server log, where they help; in the interface they are noise.
 */
export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return redactText(error.message);
  if (typeof error === "string" && error) return redactText(error);
  return fallback;
}

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

interface JobEventErrorLike {
  job?: {
    error?: {
      message?: string | null;
    } | null;
  } | null;
}

export function jobEventErrorMessage(event: JobEventErrorLike, fallback: string): string {
  return errorMessage(event.job?.error?.message, fallback);
}
