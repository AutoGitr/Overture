import Image from "@lucide/svelte/icons/image";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import StatusTab from "../../../lib/components/StatusTab.svelte";

const tab = { icon: Image, label: "Poster", clearLabel: "Clear poster" };

describe("StatusTab", () => {
  it("opens the section from its label and forgets its selection from its icon", async () => {
    const onselect = vi.fn();
    const onclear = vi.fn();
    render(StatusTab, { props: { ...tab, status: "success", onselect, onclear } });

    const posterTab = screen.getByRole("tab", { name: "Poster" });
    expect(posterTab).toHaveAttribute("aria-selected", "false");
    await fireEvent.click(posterTab);
    expect(onselect).toHaveBeenCalledOnce();
    expect(onclear).not.toHaveBeenCalled();

    const clear = screen.getByRole("button", { name: "Clear poster" });
    expect(clear.querySelector(".status-icon")).toHaveAttribute("data-status", "success");
    await fireEvent.click(clear);
    expect(onclear).toHaveBeenCalledOnce();
    expect(onselect).toHaveBeenCalledOnce();
  });

  it("keeps the icon in the label while there is nothing to forget", () => {
    render(StatusTab, { props: { ...tab, status: "danger", onselect: vi.fn() } });

    expect(screen.queryByRole("button", { name: "Clear poster" })).not.toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Poster" }).querySelector(".status-icon"),
    ).toHaveAttribute("data-status", "danger");
  });

  it("only names the panel shown when it has nothing to open, and holds clearing while busy", () => {
    const { container } = render(StatusTab, {
      props: { ...tab, active: true, status: null, onclear: vi.fn(), clearDisabled: true },
    });

    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Clear poster" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "Poster" })).toHaveAttribute("aria-selected", "true");
    expect(container.querySelector(".status-tab")).toHaveClass("active");
    expect(container.querySelector("[data-status]")).toBeNull();
  });
});
