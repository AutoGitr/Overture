export function formatDateInTimezone(iso: string, timezoneLabel?: string | null): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: timezoneLabel ?? undefined,
    });
  } catch {
    return iso;
  }
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/** A length of time: "250ms", "4.5s", "2m 3s" or "1h 2m 3s". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !(seconds >= 0)) return "";
  if (seconds > 0 && seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${Number(seconds.toFixed(1))}s`;
  const whole = Math.floor(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = `${minutes}m ${whole % 60}s`;
  return hours > 0 ? `${hours}h ${rest}` : rest;
}
