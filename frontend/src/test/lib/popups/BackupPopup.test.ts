import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getBackupScheduleOptions,
  listBackupsOptions,
} from "../../../generated/rest/@tanstack/svelte-query.gen";
import BackupPopup from "../../../lib/popups/BackupPopup.svelte";
import { invalidateTags } from "../../../lib/rest/cache";
import { queryClient } from "../../../lib/rest/queryClient";
import { ApiError } from "../../../lib/rest/transport";
import { backupState } from "../../../lib/stores/jobStates.svelte";
import { renderWithQueryClient } from "../../helpers/render";

const { getBackupSchedule, listBackups, updateBackupSchedule, createBackup } = vi.hoisted(() => ({
  getBackupSchedule: vi.fn(),
  listBackups: vi.fn(),
  updateBackupSchedule: vi.fn(),
  createBackup: vi.fn(),
}));
vi.mock("../../../generated/rest/sdk.gen", () => ({
  getBackupSchedule,
  listBackups,
  updateBackupSchedule,
  createBackup,
}));
const schedule = {
  enabled: true,
  cron_expression: "0 4 * * *",
  retention: { latest: 2, daily: 7, weekly: 4, monthly: 6 },
  next_run: null,
  timezone: "UTC",
  updated_at: null,
};
const backups = {
  backups: [
    { filename: "overture-backup.zip", size_bytes: 2048, created_at: "2026-09-04T10:00:00Z" },
  ],
};

describe("BackupPopup", () => {
  beforeEach(() => {
    queryClient.clear();
    backupState.reset();
    getBackupSchedule.mockResolvedValue({ data: schedule });
    listBackups.mockResolvedValue({ data: backups });
    updateBackupSchedule.mockResolvedValue({ data: schedule });
    createBackup.mockResolvedValue({ data: { status: "ok", filename: "overture-backup.zip" } });
  });

  it("keeps the schedule locked until a failed read is successfully retried", async () => {
    getBackupSchedule.mockRejectedValue(new ApiError("Schedule unavailable", 403));
    renderWithQueryClient(BackupPopup);
    expect(screen.getByRole("button", { name: "Save Schedule" })).toBeDisabled();
    expect(await screen.findByRole("alert")).toHaveTextContent("Schedule unavailable");
    expect(screen.getByLabelText("Cron expression")).toBeDisabled();
    getBackupSchedule.mockResolvedValue({ data: schedule });
    await fireEvent.click(screen.getByRole("button", { name: "Retry backup schedule" }));
    await waitFor(() => expect(screen.getByLabelText("Cron expression")).toHaveValue("0 4 * * *"));
    await fireEvent.input(screen.getByLabelText("Cron expression"), {
      target: { value: "0 6 * * *" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save Schedule" }));
    await waitFor(() =>
      expect(updateBackupSchedule).toHaveBeenCalledWith({
        body: {
          enabled: true,
          cron_expression: "0 6 * * *",
          retention: { latest: 2, daily: 7, weekly: 4, monthly: 6 },
        },
        throwOnError: true,
      }),
    );
  });

  it("saves how many latest, daily, weekly and monthly backups to keep", async () => {
    renderWithQueryClient(BackupPopup);
    const monthly = await screen.findByRole("spinbutton", { name: "Monthly" });
    expect(screen.getByRole("spinbutton", { name: "Latest" })).toHaveValue(2);
    await fireEvent.input(monthly, { target: { value: "12" } });
    await fireEvent.input(screen.getByRole("spinbutton", { name: "Weekly" }), {
      target: { value: "0" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save Schedule" }));
    await waitFor(() =>
      expect(updateBackupSchedule).toHaveBeenCalledWith({
        body: {
          enabled: true,
          cron_expression: "0 4 * * *",
          retention: { latest: 2, daily: 7, weekly: 0, monthly: 12 },
        },
        throwOnError: true,
      }),
    );
  });

  it("reports an unavailable backup list and retries to a genuine empty result", async () => {
    listBackups.mockRejectedValue(new ApiError("Backups unavailable", 403));
    renderWithQueryClient(BackupPopup);
    expect(await screen.findByRole("alert")).toHaveTextContent("Backups unavailable");
    expect(screen.queryByText("No backups yet.")).not.toBeInTheDocument();
    listBackups.mockResolvedValue({ data: { backups: [] } });
    await fireEvent.click(screen.getByRole("button", { name: "Retry backups" }));
    expect(await screen.findByText("No backups yet.")).toBeInTheDocument();
  });

  it("preserves the backup list and schedule draft through background refresh failures", async () => {
    queryClient.setQueryData(getBackupScheduleOptions().queryKey, schedule);
    queryClient.setQueryData(listBackupsOptions().queryKey, backups);
    renderWithQueryClient(BackupPopup);
    await fireEvent.input(screen.getByLabelText("Cron expression"), {
      target: { value: "0 6 * * *" },
    });
    listBackups.mockRejectedValue(new ApiError("Backups unavailable", 403));
    await invalidateTags(["backups"]);
    expect(await screen.findByRole("alert")).toHaveTextContent("Showing last loaded data.");
    expect(screen.getByText("overture-backup.zip")).toBeVisible();
    expect(screen.getByLabelText("Cron expression")).toHaveValue("0 6 * * *");
    listBackups.mockResolvedValue({ data: backups });
    await fireEvent.click(screen.getByRole("button", { name: "Retry backups" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("reports a backup failure safely and permits an explicit retry", async () => {
    createBackup.mockRejectedValueOnce(new ApiError("token=secret", 503));
    renderWithQueryClient(BackupPopup);
    await fireEvent.click(screen.getByRole("button", { name: "Backup Now" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("token=[REDACTED]");
    await fireEvent.click(screen.getByRole("button", { name: "Backup Now" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved overture-backup.zip.");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
