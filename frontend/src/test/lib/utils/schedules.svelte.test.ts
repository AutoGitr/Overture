import { describe, expect, it, vi } from "vitest";
import type { SyncScheduleResponse } from "../../../generated/rest/types.gen";
import { ApiError } from "../../../lib/rest/transport";
import { notificationState } from "../../../lib/stores/notificationState.svelte";
import { formatDateInTimezone } from "../../../lib/utils/popupFormat";
import {
  buildScheduleWrite,
  formatScheduleDate,
  ScheduleController,
  type ScheduleControllerOptions,
} from "../../../lib/utils/schedules.svelte";
import { answerConfirmation } from "../../helpers/notifications";

type Config = SyncScheduleResponse["config"];
type Schedule = SyncScheduleResponse;

const config: Config = {
  mode: "full",
  library_ids: ["1"],
  download_overturedb_art: false,
  download_themes: "off",
};

function schedule(overrides: Partial<Schedule> = {}): Schedule {
  return {
    id: 3,
    kind: "sync",
    name: "Nightly",
    enabled: true,
    cron_expression: "0 3 * * *",
    timezone: "UTC",
    next_run: null,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    last_run_at: null,
    run_status: "idle",
    waiting_for: null,
    config,
    state: {
      checkpoint: null,
      last_duration_seconds: null,
      last_items_added: null,
      last_downloads: null,
    },
    ...overrides,
  };
}

function mutation() {
  return { mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false };
}

function controller(list: Partial<ScheduleControllerOptions<Config, Schedule>["list"]> = {}) {
  const options = {
    list: {
      data: [schedule()],
      isPending: false,
      isFetching: false,
      error: null,
      refetch: vi.fn().mockResolvedValue(undefined),
      ...list,
    },
    create: mutation(),
    update: mutation(),
    remove: mutation(),
    run: mutation(),
  };
  return { options, schedules: new ScheduleController<Config, Schedule>(options) };
}

const toasts = () => notificationState.toasts.map(({ tone, message }) => `${tone}: ${message}`);

describe("schedule writes and dates", () => {
  it("trims the name and cron expression a form sends", () => {
    expect(
      buildScheduleWrite({
        name: "  Nightly ",
        enabled: false,
        cronExpression: " 0 3 * * * ",
        config,
      }),
    ).toEqual({ name: "Nightly", enabled: false, cron_expression: "0 3 * * *", config });
  });

  it("formats a scheduled date in the server's timezone, or says there is none", () => {
    const at = "2026-03-01T12:00:00Z";

    expect(formatScheduleDate(at, "UTC")).toBe(formatDateInTimezone(at, "UTC"));
    expect(formatScheduleDate(null, "UTC")).toBe("Not scheduled");
  });
});

describe("ScheduleController", () => {
  it("reads the list it was given", () => {
    const { schedules } = controller({ data: undefined, isPending: true, isFetching: true });

    expect(schedules.schedules).toEqual([]);
    expect(schedules.loading).toBe(true);
    expect(schedules.fetching).toBe(true);
    expect(schedules.error).toBeNull();
  });

  it("saves a new schedule, clears the form and reloads the list", async () => {
    const { options, schedules } = controller();
    schedules.name = " Weekly ";
    schedules.enabled = false;

    await schedules.save("0 4 * * 0", config);

    expect(options.create.mutateAsync).toHaveBeenCalledWith({
      body: { name: "Weekly", enabled: false, cron_expression: "0 4 * * 0", config },
    });
    expect(options.list.refetch).toHaveBeenCalledOnce();
    expect([schedules.name, schedules.enabled]).toEqual(["", true]);
    expect(toasts()).toContain("success: Schedule saved.");
  });

  it("updates the schedule being edited", async () => {
    const { options, schedules } = controller();
    schedules.beginEdit(schedule({ id: 7, name: "Old", enabled: false }));
    expect([schedules.isEditing, schedules.expandedId, schedules.name]).toEqual([true, 7, "Old"]);

    await schedules.save("0 5 * * *", config);

    expect(options.update.mutateAsync).toHaveBeenCalledWith({
      body: { name: "Old", enabled: false, cron_expression: "0 5 * * *", config },
      path: { schedule_id: 7 },
    });
    expect(schedules.isEditing).toBe(false);
    expect(toasts()).toContain("success: Schedule updated.");
  });

  it("keeps the form when saving fails", async () => {
    const { options, schedules } = controller();
    options.create.mutateAsync.mockRejectedValue(new ApiError("Invalid cron", 422));
    schedules.name = "Broken";

    await schedules.save("bad", config);

    expect(schedules.name).toBe("Broken");
    expect(options.list.refetch).not.toHaveBeenCalled();
    expect(toasts()).toContain("error: Invalid cron");
  });

  it("switches a schedule on or off with its saved settings", async () => {
    const { options, schedules } = controller();
    const nightly = schedule();

    await schedules.setEnabled(nightly, false);

    expect(options.update.mutateAsync).toHaveBeenCalledWith({
      body: { name: "Nightly", enabled: false, cron_expression: "0 3 * * *", config },
      path: { schedule_id: 3 },
    });
    expect(options.list.refetch).toHaveBeenCalledOnce();

    options.update.mutateAsync.mockRejectedValue(new ApiError("Schedule locked", 409));
    await schedules.setEnabled(nightly, true);
    expect(toasts()).toContain("error: Schedule locked");
  });

  it("removes a schedule only once confirmed, ending its edit", async () => {
    const { options, schedules } = controller();
    const nightly = schedule();
    schedules.beginEdit(nightly);

    const declined = schedules.remove(nightly);
    expect((await answerConfirmation(false)).title).toBe('Remove schedule "Nightly"?');
    await declined;
    expect(options.remove.mutateAsync).not.toHaveBeenCalled();

    const confirmed = schedules.remove(nightly);
    await answerConfirmation(true);
    await confirmed;
    expect(options.remove.mutateAsync).toHaveBeenCalledWith({ path: { schedule_id: 3 } });
    expect(schedules.isEditing).toBe(false);
    expect(options.list.refetch).toHaveBeenCalledOnce();
  });

  it("reports a failed removal", async () => {
    const { options, schedules } = controller();
    options.remove.mutateAsync.mockRejectedValue(new ApiError("Schedule is running", 409));

    const removal = schedules.remove(schedule());
    await answerConfirmation(true);
    await removal;

    expect(toasts()).toContain("error: Schedule is running");
  });

  it("queues a schedule to run now and says so", async () => {
    const { options, schedules } = controller();

    await schedules.runNow(schedule());
    expect(options.run.mutateAsync).toHaveBeenCalledWith({ path: { schedule_id: 3 } });
    expect(toasts()).toContain('success: "Nightly" queued.');

    options.run.mutateAsync.mockRejectedValue(new ApiError("Already queued", 409));
    await schedules.runNow(schedule());
    expect(toasts()).toContain("error: Already queued");
  });

  it("expands one schedule at a time", () => {
    const { schedules } = controller();

    schedules.toggleExpanded(1);
    schedules.toggleExpanded(2);
    expect(schedules.expandedId).toBe(2);

    schedules.toggleExpanded(2);
    expect(schedules.expandedId).toBeNull();
  });
});
