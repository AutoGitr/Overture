import { fireEvent, render, screen } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import { describe, expect, it, vi } from "vitest";
import PopupShell from "../../../lib/components/PopupShell.svelte";

const children = createRawSnippet(() => ({ render: () => "<p>Dialog content</p>" }));

describe("PopupShell", () => {
  it("opens a named modal, focuses its close control, and restores the opener", async () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const view = render(PopupShell, { title: "Test dialog", children, onclose: vi.fn() });
    const dialog = screen.getByRole("dialog", { name: "Test dialog" });
    expect(dialog).toHaveAttribute("open");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("button", { name: "Close popup" })).toHaveFocus();
    await view.unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("handles cancellation through the owner", async () => {
    const onclose = vi.fn();
    render(PopupShell, { title: "Test dialog", children, onclose });
    const event = new Event("cancel", { cancelable: true });
    await fireEvent(screen.getByRole("dialog"), event);
    expect(event.defaultPrevented).toBe(true);
    expect(onclose).toHaveBeenCalledOnce();
  });

  it("closes on a backdrop click but not a drag out of the content", async () => {
    const onclose = vi.fn();
    render(PopupShell, { title: "Test dialog", children, onclose });
    const dialog = screen.getByRole("dialog");
    await fireEvent.pointerDown(screen.getByText("Dialog content"));
    await fireEvent.click(dialog);
    expect(onclose).not.toHaveBeenCalled();
    await fireEvent.pointerDown(dialog);
    await fireEvent.click(dialog);
    expect(onclose).toHaveBeenCalledOnce();
  });
});
