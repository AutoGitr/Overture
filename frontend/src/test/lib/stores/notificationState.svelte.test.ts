import { describe, expect, it } from "vitest";
import {
  confirmAction,
  createNotifier,
  notificationState,
  notify,
} from "../../../lib/stores/notificationState.svelte";

describe("notificationState", () => {
  it("restarts a repeated message instead of stacking copies, and caps the stack", () => {
    const first = notify.error("Failed.");
    notify.info("One.");
    const repeat = notify.error("Failed.");
    expect(repeat).not.toBe(first);
    expect(notificationState.toasts.map((toast) => toast.message)).toEqual(["One.", "Failed."]);

    for (const message of ["A", "B", "C", "D"]) notify.info(message);
    expect(notificationState.toasts.map((toast) => toast.message)).toEqual(["A", "B", "C", "D"]);
  });

  it("gives each notifier one slot that new messages replace and retries clear", () => {
    const feedback = createNotifier();
    notify.info("Unrelated.");
    feedback.error("Stop failed.");
    feedback.warning("Wait for the scan.");
    expect(notificationState.toasts.map((toast) => toast.message)).toEqual([
      "Unrelated.",
      "Wait for the scan.",
    ]);
    feedback.clear();
    expect(notificationState.toasts.map((toast) => toast.message)).toEqual(["Unrelated."]);
  });

  it("resolves a confirmation with the answer and declines one it replaces", async () => {
    const first = confirmAction({ title: "First?", message: "One." });
    const second = confirmAction({ title: "Second?", message: "Two." });
    await expect(first).resolves.toBe(false);
    expect(notificationState.confirmRequest?.title).toBe("Second?");
    notificationState.settleConfirm(true);
    await expect(second).resolves.toBe(true);
    expect(notificationState.confirmRequest).toBeNull();
  });
});
