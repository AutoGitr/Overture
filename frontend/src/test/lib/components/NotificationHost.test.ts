import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { createRawSnippet, tick } from "svelte";
import { describe, expect, it, vi } from "vitest";
import PopupShell from "../../../lib/components/PopupShell.svelte";
import {
  confirmAction,
  notify,
  TOAST_DURATION_MS,
} from "../../../lib/stores/notificationState.svelte";

const children = createRawSnippet(() => ({ render: () => "<p>Popup content</p>" }));

describe("toasts", () => {
  it.each(["success", "info", "warning", "error"] as const)(
    "closes a %s toast on its own after the shared duration",
    async (tone) => {
      vi.useFakeTimers();
      notify[tone]("Something happened.");
      await tick();
      expect(screen.getByText("Something happened.")).toBeInTheDocument();
      vi.advanceTimersByTime(TOAST_DURATION_MS - 1);
      await tick();
      expect(screen.getByText("Something happened.")).toBeInTheDocument();
      vi.advanceTimersByTime(1);
      await tick();
      expect(screen.queryByText("Something happened.")).not.toBeInTheDocument();
    },
  );

  it("holds a toast open while hovered and resumes the remaining time after", async () => {
    vi.useFakeTimers();
    notify.error("Rename failed.");
    await tick();
    const toast = screen.getByRole("alert");
    vi.advanceTimersByTime(TOAST_DURATION_MS / 2);
    await fireEvent.pointerEnter(toast.parentElement as HTMLElement);
    vi.advanceTimersByTime(60_000);
    await tick();
    expect(screen.getByRole("alert")).toBeInTheDocument();

    await fireEvent.pointerLeave(toast.parentElement as HTMLElement);
    vi.advanceTimersByTime(TOAST_DURATION_MS / 2);
    await tick();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps its countdown when a popup moves it", async () => {
    vi.useFakeTimers();
    notify.success("Saved.");
    await tick();
    vi.advanceTimersByTime(TOAST_DURATION_MS - 1000);

    // Opening a modal re-renders the toast inside it.
    render(PopupShell, { title: "Operations", children, onclose: vi.fn() });
    await tick();
    expect(within(screen.getByRole("dialog")).getByRole("status")).toBeInTheDocument();

    vi.advanceTimersByTime(1000);
    await tick();
    expect(screen.queryByText("Saved.")).not.toBeInTheDocument();
  });

  it("can still be closed early", async () => {
    notify.error("Rename failed.");
    await tick();
    const toast = screen.getByRole("alert");
    await fireEvent.click(within(toast).getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("runs a toast's action and then closes it", async () => {
    const run = vi.fn();
    notify.warning("Results changed.", { action: { label: "Reload", run } });
    await tick();
    await fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(run).toHaveBeenCalledOnce();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders inside the open modal so it stays interactive above it", async () => {
    render(PopupShell, { title: "Operations", children, onclose: vi.fn() });
    notify.error("Scan failed.");
    await tick();
    const dialog = screen.getByRole("dialog", { name: "Operations" });
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Scan failed.");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });
});

describe("confirmation dialog", () => {
  it("starts a destructive confirmation on Cancel and resolves the answer", async () => {
    const answer = confirmAction({
      title: "Remove schedule?",
      message: "The saved schedule stops running and is deleted.",
      confirmLabel: "Remove",
      destructive: true,
    });
    await tick();
    const dialog = screen.getByRole("dialog", { name: "Remove schedule?" });
    expect(dialog).toHaveTextContent("The saved schedule stops running and is deleted.");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await expect(answer).resolves.toBe(true);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("treats Escape as cancel", async () => {
    const answer = confirmAction({ title: "Monitor 2 movies?", message: "Two movies." });
    await tick();
    const dialog = screen.getByRole("dialog", { name: "Monitor 2 movies?" });
    expect(within(dialog).getByRole("button", { name: "Confirm" })).toHaveFocus();
    await fireEvent(dialog, new Event("cancel", { cancelable: true }));
    await expect(answer).resolves.toBe(false);
  });
});
