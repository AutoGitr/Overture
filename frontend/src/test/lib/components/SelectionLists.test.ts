import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import CheckboxList from "../../../lib/components/CheckboxList.svelte";
import LibraryChecklist from "../../../lib/components/LibraryChecklist.svelte";

describe("selection lists", () => {
  it("updates checkbox membership when selection props change", async () => {
    const ontoggle = vi.fn();
    const { rerender } = render(CheckboxList, {
      options: [
        { value: "first", label: "First" },
        { value: "second", label: "Second" },
      ],
      selected: ["first"],
      ontoggle,
    });
    expect(screen.getByRole("checkbox", { name: "First" })).toBeChecked();
    await rerender({ selected: ["second"] });
    expect(screen.getByRole("checkbox", { name: "First" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Second" })).toBeChecked();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Second" }));
    expect(ontoggle).toHaveBeenCalledWith("second");
  });

  it("updates libraries and select-all when the selected IDs change", async () => {
    const { rerender } = render(LibraryChecklist, {
      movieLibraries: [{ id: "movies", title: "Films" }],
      showLibraries: [{ id: "shows", title: "Series" }],
      selectedIds: ["movies"],
      ontoggle: vi.fn(),
      ontoggleall: vi.fn(),
    });
    expect(screen.getByRole("checkbox", { name: "Films" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select All" })).not.toBeChecked();
    await rerender({ selectedIds: ["shows"] });
    expect(screen.getByRole("checkbox", { name: "Films" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Series" })).toBeChecked();
    await rerender({ selectedIds: ["movies", "shows"] });
    expect(screen.getByRole("checkbox", { name: "Deselect All" })).toBeChecked();
  });
});
