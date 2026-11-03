/** A named cron expression a schedule form offers as a shortcut. */
export interface CronPreset {
  label: string;
  value: string;
}

const PRESET = {
  quarterHourly: { label: "Every 15 min", value: "*/15 * * * *" },
  halfHourly: { label: "Every 30 min", value: "*/30 * * * *" },
  hourly: { label: "Hourly", value: "0 * * * *" },
  sixHourly: { label: "Every 6h", value: "0 */6 * * *" },
  daily: { label: "Daily 03:00", value: "0 3 * * *" },
  weekly: { label: "Weekly Sun 03:00", value: "0 3 * * 0" },
} as const satisfies Record<string, CronPreset>;

/** Long-running work: syncs, asset runs and backups. */
export const ROUTINE_CRON_PRESETS: readonly CronPreset[] = [
  PRESET.hourly,
  PRESET.sixHourly,
  PRESET.daily,
  PRESET.weekly,
];

/** Polling that only looks for new media, so it can run often. */
export const POLLING_CRON_PRESETS: readonly CronPreset[] = [
  PRESET.quarterHourly,
  PRESET.halfHourly,
  PRESET.hourly,
  PRESET.sixHourly,
];

/** The schedule a new routine job starts from. */
export const DEFAULT_CRON_EXPRESSION: string = PRESET.daily.value;
