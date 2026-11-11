import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import CheckboxList from "../../../lib/components/CheckboxList.svelte";
import CollectionChecklist from "../../../lib/components/CollectionChecklist.svelte";
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
    expect(screen.getByRole("checkbox", { name: "Select all libraries" })).not.toBeChecked();
    await rerender({ selectedIds: ["shows"] });
    expect(screen.getByRole("checkbox", { name: "Films" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Series" })).toBeChecked();
    await rerender({ selectedIds: ["movies", "shows"] });
    expect(screen.getByRole("checkbox", { name: "Deselect all libraries" })).toBeChecked();
  });
  it("chooses collections apart from libraries, every collection including every group", async () => {
    const onchange = vi.fn();
    const { rerender } = render(CollectionChecklist, {
      groups: ["Sagas", "Studios"],
      choice: { all: true, groups: [] },
      onchange,
    });
    expect(screen.getByRole("checkbox", { name: "Sagas" })).toBeChecked();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Sagas" }));
    expect(onchange).toHaveBeenLastCalledWith({ all: false, groups: ["Studios"] });
    await rerender({ choice: { all: false, groups: [] } });
    await fireEvent.click(screen.getByRole("checkbox", { name: "Select all collections" }));
    expect(onchange).toHaveBeenLastCalledWith({ all: true, groups: [] });
  });

  it("offers single collections, chosen with their group or by themselves", async () => {
    const oncollectionschange = vi.fn();
    render(CollectionChecklist, {
      groups: ["Sagas", "Ungrouped"],
      choice: { all: false, groups: ["Sagas"] },
      onchange: vi.fn(),
      collections: [
        { id: 1, title: "Alien", group: "Sagas" },
        { id: 2, title: "Pixar", group: "Ungrouped" },
      ],
      collectionIds: [],
      oncollectionschange,
    });
    expect(screen.getByRole("checkbox", { name: "Alien" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Alien" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Pixar" }));
    expect(oncollectionschange).toHaveBeenCalledWith([2]);
  });
});
