/** Return elapsed whole seconds from `startedAt` to `end` (a timestamp or epoch milliseconds). */
export function elapsedSeconds(startedAt: string, end: string | number): number {
  const start = Date.parse(startedAt);
  const finish = typeof end === "number" ? end : Date.parse(end);
  if (Number.isNaN(start) || Number.isNaN(finish)) return 0;
  return Math.max(0, Math.floor((finish - start) / 1000));
}
