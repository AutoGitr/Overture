import { formatDuration } from "./popupFormat";

/** Format the time from `startedAt` to `end` (a timestamp or epoch milliseconds). */
export function formatElapsedTime(startedAt: string, end: string | number): string {
  const start = Date.parse(startedAt);
  const finish = typeof end === "number" ? end : Date.parse(end);
  if (Number.isNaN(start) || Number.isNaN(finish)) return "";
  return formatDuration(Math.max(0, Math.floor((finish - start) / 1000)));
}
