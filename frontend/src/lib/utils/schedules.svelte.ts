import { SvelteSet } from "svelte/reactivity";
import type {
  BulkAssetsScheduleResponse,
  BulkAssetsScheduleWrite,
  ScheduleRunSummary,
  SyncScheduleResponse,
  SyncScheduleWrite,
} from "../../generated/rest/types.gen";
import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
import { errorMessage } from "./errors";
import { formatDateInTimezone, formatDuration } from "./popupFormat";

/** One mutation handle, as returned by `createMutation`. */
interface Mutation<TVariables> {
  mutateAsync: (variables: TVariables) => Promise<unknown>;
  isPending: boolean;
}

/** The request body every saved-schedule create and update shares. */
export type ScheduleWrite<TConfig> = Omit<SyncScheduleWrite | BulkAssetsScheduleWrite, "config"> & {
  config: TConfig;
};

/** The fields every saved schedule response shares, whatever it configures. */
export type SavedSchedule<TConfig> = Omit<
  SyncScheduleResponse | BulkAssetsScheduleResponse,
  "config" | "kind"
> & { config: TConfig };

/** The schedule list, as `createQuery` returns it. */
interface ScheduleList<TSchedule> {
  data: TSchedule[] | undefined;
  isPending: boolean;
  isFetching: boolean;
  error: unknown;
  refetch: () => Promise<unknown>;
}

export interface ScheduleControllerOptions<TConfig, TSchedule extends SavedSchedule<TConfig>> {
  /** The saved schedules; realtime announcements invalidate it. */
  list: ScheduleList<TSchedule>;
  create: Mutation<{ body: ScheduleWrite<TConfig> }>;
  update: Mutation<{ body: ScheduleWrite<TConfig>; path: { schedule_id: number } }>;
  remove: Mutation<{ path: { schedule_id: number } }>;
  run: Mutation<{ path: { schedule_id: number } }>;
}

/** Build the request body used to create or update a saved schedule. */
export function buildScheduleWrite<TConfig>(params: {
  name: string;
  enabled: boolean;
  cronExpression: string;
  config: TConfig;
}): ScheduleWrite<TConfig> {
  return {
    name: params.name.trim(),
    enabled: params.enabled,
    cron_expression: params.cronExpression.trim(),
    config: params.config,
  };
}

/** Format a schedule date in the given timezone, or a placeholder when unset. */
export function formatScheduleDate(value: string | null | undefined, timezone: string): string {
  return value ? formatDateInTimezone(value, timezone) : "Not scheduled";
}

/** What a schedule's last run did: "41s, 12 queued, 1 failed" or "Failed after 3s". */
export function formatRunSummary(summary: ScheduleRunSummary): string {
  const duration = formatDuration(summary.duration_seconds);
  const counts = Object.entries(summary.counts ?? {}).map(([name, count]) => `${count} ${name}`);
  const parts = [
    summary.failed ? `failed${duration && ` after ${duration}`}` : duration,
    ...counts,
  ];
  const text = parts.filter(Boolean).join(", ") || "nothing to do";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * Saved-schedule state and CRUD for one operation's schedule panel.
 *
 * Kept out of the operation tab so the tab owns only the run/results flow;
 * the schedule list, its edit form, and the calls behind them live together.
 */
export class ScheduleController<TConfig, TSchedule extends SavedSchedule<TConfig>> {
  name = $state("");
  editingId = $state<number | null>(null);
  expandedIds = new SvelteSet<number>();

  isExpanded(id: number): boolean {
    return this.expandedIds.has(id);
  }

  private options: ScheduleControllerOptions<TConfig, TSchedule>;
  private feedback = createNotifier();

  constructor(options: ScheduleControllerOptions<TConfig, TSchedule>) {
    this.options = options;
  }

  get schedules(): TSchedule[] {
    return this.options.list.data ?? [];
  }

  get loading(): boolean {
    return this.options.list.isPending;
  }

  get fetching(): boolean {
    return this.options.list.isFetching;
  }

  /** Why the list could not be loaded, or `null`. */
  get error(): unknown {
    return this.options.list.error;
  }

  /** Load the list again, as after each change made here. */
  async reload() {
    await this.options.list.refetch();
  }

  get isEditing(): boolean {
    return this.editingId !== null;
  }

  get runPending(): boolean {
    return this.options.run.isPending;
  }

  get removePending(): boolean {
    return this.options.remove.isPending;
  }

  /**
   * Save the given configuration as a new schedule, or update the edited one.
   * The list's checkbox alone turns a schedule on or off: a new one starts
   * enabled, and an update keeps the state the list shows.
   */
  async save(cronExpression: string, config: TConfig) {
    this.feedback.clear();
    try {
      const body = buildScheduleWrite({
        name: this.name,
        enabled: this.schedules.find((schedule) => schedule.id === this.editingId)?.enabled ?? true,
        cronExpression,
        config,
      });
      if (this.editingId !== null) {
        await this.options.update.mutateAsync({
          body,
          path: { schedule_id: this.editingId },
        });
        this.feedback.success("Schedule updated.");
      } else {
        await this.options.create.mutateAsync({ body });
        this.feedback.success("Schedule saved.");
      }
      this.clearEdit();
      await this.reload();
    } catch (err) {
      this.feedback.error(errorMessage(err, "Failed to save schedule"));
    }
  }

  /** Mark a saved schedule as the one the form edits. */
  beginEdit(schedule: TSchedule) {
    this.editingId = schedule.id;
    this.expandedIds.add(schedule.id);
    this.name = schedule.name;
  }

  clearEdit() {
    this.editingId = null;
    this.name = "";
  }

  async setEnabled(schedule: TSchedule, enabled: boolean) {
    this.feedback.clear();
    try {
      await this.options.update.mutateAsync({
        body: {
          name: schedule.name,
          enabled,
          cron_expression: schedule.cron_expression,
          config: schedule.config,
        },
        path: { schedule_id: schedule.id },
      });
      await this.reload();
    } catch (err) {
      this.feedback.error(errorMessage(err, "Failed to update schedule"));
    }
  }

  async remove(schedule: TSchedule) {
    const confirmed = await confirmAction({
      title: `Remove schedule "${schedule.name}"?`,
      message: "The saved schedule stops running and is deleted.",
      confirmLabel: "Remove",
      destructive: true,
    });
    if (!confirmed) return;
    this.feedback.clear();
    try {
      await this.options.remove.mutateAsync({ path: { schedule_id: schedule.id } });
      this.expandedIds.delete(schedule.id);
      if (this.editingId === schedule.id) this.clearEdit();
      await this.reload();
    } catch (err) {
      this.feedback.error(errorMessage(err, "Failed to remove schedule"));
    }
  }

  async runNow(schedule: TSchedule) {
    this.feedback.clear();
    try {
      await this.options.run.mutateAsync({ path: { schedule_id: schedule.id } });
      this.feedback.success(`"${schedule.name}" queued.`);
      await this.reload();
    } catch (err) {
      this.feedback.error(errorMessage(err, "Failed to run schedule"));
    }
  }

  toggleExpanded(id: number) {
    if (this.expandedIds.has(id)) {
      this.expandedIds.delete(id);
    } else {
      this.expandedIds.add(id);
    }
  }
}
