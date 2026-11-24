import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Select from "../../../lib/components/Select.svelte";

const OPTIONS = [
  { value: "first", label: "First", group: "Primary", detail: "10" },
  { value: "locked", label: "Locked", group: "Primary", disabled: true },
  { value: "last", label: "Last", group: "Secondary" },
] as const;

describe("Select", () => {
  it("opens its listbox with groups and details, skips disabled options, and closes on outside press", async () => {
    render(Select, { label: "Choice", value: "first", options: OPTIONS });

    const trigger = screen.getByRole("combobox", { name: "Choice" });
    expect(trigger).toHaveTextContent("First");

    await fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(screen.getByText("Primary")).toBeInTheDocument();
    expect(screen.getByText("Secondary")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Locked" })).toHaveAttribute("aria-disabled", "true");

    // ArrowDown from First skips disabled Locked and lands on Last.
    await fireEvent.keyDown(trigger, { key: "ArrowDown" });
    await fireEvent.keyDown(trigger, { key: "Enter" });
    expect(trigger).toHaveTextContent("Last");
    expect(screen.queryByRole("listbox")).toBeNull();

    // Home, End and Escape navigate and dismiss without changing the value.
    await fireEvent.click(trigger);
    await fireEvent.keyDown(trigger, { key: "Home" });
    await fireEvent.keyDown(trigger, { key: "End" });
    await fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();

    await fireEvent.click(trigger);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("shows its placeholder for a value no option holds", () => {
    render(Select, {
      label: "Choice",
      value: null,
      placeholder: "Choose one",
      options: OPTIONS,
    });

    expect(screen.getByRole("combobox", { name: "Choice" })).toHaveTextContent("Choose one");
  });

  it("jumps to the enabled option a typed letter starts", async () => {
    render(Select, { label: "Choice", value: "first", options: OPTIONS });

    const trigger = screen.getByRole("combobox", { name: "Choice" });
    // Locked starts with L too, but is disabled.
    await fireEvent.keyDown(trigger, { key: "l" });
    expect(trigger).toHaveAttribute(
      "aria-activedescendant",
      screen.getByRole("option", { name: "Last" }).id,
    );
    await fireEvent.keyDown(trigger, { key: "Enter" });
    expect(trigger).toHaveTextContent("Last");
  });

  it("stays closed while disabled", async () => {
    render(Select, {
      label: "Choice",
      value: "first",
      disabled: true,
      options: OPTIONS,
    });

    const trigger = screen.getByRole("combobox", { name: "Choice" });
    expect(trigger).toBeDisabled();
    await fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("positions popover listboxes within the viewport and closes on outside scroll or Tab", async () => {
    const showPopover = vi.fn();
    Object.defineProperty(HTMLUListElement.prototype, "showPopover", {
      configurable: true,
      value: showPopover,
    });
    Object.defineProperty(document.documentElement, "clientWidth", {
      configurable: true,
      value: 800,
    });
    Object.defineProperty(document.documentElement, "clientHeight", {
      configurable: true,
      value: 600,
    });

    try {
      render(Select, {
        label: "Choice",
        value: "first",
        options: OPTIONS,
      });
      const trigger = screen.getByRole("combobox", { name: "Choice" });

      // Near the top of the screen: opens below, stays open on internal scroll, closes on Tab.
      vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue(new DOMRect(40, 20, 160, 36));
      await fireEvent.keyDown(trigger, { key: "ArrowUp" });
      const below = screen.getByRole("listbox");
      expect(showPopover).toHaveBeenCalledTimes(1);
      expect(below.style.top).toBe("58px");
      await fireEvent.scroll(below);
      expect(screen.getByRole("listbox")).toBeInTheDocument();
      await fireEvent.keyDown(trigger, { key: "Tab" });
      expect(screen.queryByRole("listbox")).toBeNull();

      // Near the bottom of the screen: flips above, tracks ancestor scroll, and closes off-screen.
      const rectSpy = vi
        .spyOn(trigger, "getBoundingClientRect")
        .mockReturnValue(new DOMRect(40, 560, 160, 36));
      await fireEvent.click(trigger);
      const above = screen.getByRole("listbox");
      expect(above.style.bottom).toBe("42px");
      await fireEvent.keyDown(screen.getByRole("option", { name: "Last" }), { key: "Enter" });
      expect(screen.queryByRole("listbox")).toBeNull();

      await fireEvent.click(trigger);
      rectSpy.mockReturnValue(new DOMRect(40, 120, 160, 36));
      await fireEvent.scroll(document.body);
      expect(screen.getByRole("listbox").style.top).toBe("158px");

      rectSpy.mockReturnValue(new DOMRect(40, -60, 160, 36));
      await fireEvent.scroll(document.body);
      expect(screen.queryByRole("listbox")).toBeNull();
    } finally {
      Reflect.deleteProperty(HTMLUListElement.prototype, "showPopover");
    }
  });
});
