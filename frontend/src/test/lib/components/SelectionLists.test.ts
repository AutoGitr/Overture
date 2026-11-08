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
    expect(screen.getByRole("checkbox", { name: "Select all" })).not.toBeChecked();
    await rerender({ selectedIds: ["shows"] });
    expect(screen.getByRole("checkbox", { name: "Films" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Series" })).toBeChecked();
    await rerender({ selectedIds: ["movies", "shows"] });
    expect(screen.getByRole("checkbox", { name: "Deselect all" })).toBeChecked();
  });
  it("keeps collection choices separate from library IDs and includes them in select-all", async () => {
    const ontoggle = vi.fn();
    const ontoggleall = vi.fn();
    const oncollectiontoggle = vi.fn();
    const oncollectionsall = vi.fn();
    const { rerender } = render(LibraryChecklist, {
      movieLibraries: [{ id: "movies", title: "Films" }],
      showLibraries: [{ id: "shows", title: "Series" }],
      selectedIds: ["movies", "shows"],
      collectionGroups: ["Sagas"],
      collections: { all: false, groups: [] },
      ontoggle,
      ontoggleall,
      oncollectiontoggle,
      oncollectionsall,
    });
    await fireEvent.click(screen.getByRole("checkbox", { name: "Sagas" }));
    expect(oncollectiontoggle).toHaveBeenCalledWith("Sagas");
    expect(ontoggle).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole("checkbox", { name: "All collections" }));
    expect(oncollectiontoggle).toHaveBeenLastCalledWith(null);
    await rerender({ collections: { all: false, groups: ["Sagas"] } });
    await fireEvent.click(screen.getByRole("checkbox", { name: "Deselect all" }));
    expect(ontoggleall).toHaveBeenCalledWith(false);
    expect(oncollectionsall).toHaveBeenLastCalledWith(false);
    expect(ontoggle).not.toHaveBeenCalled();
  });
  it("selects only libraries when collections are not offered", async () => {
    const ontoggleall = vi.fn();
    const oncollectionsall = vi.fn();
    render(LibraryChecklist, {
      movieLibraries: [{ id: "movies", title: "Films" }],
      selectedIds: [],
      ontoggle: vi.fn(),
      ontoggleall,
      oncollectionsall,
    });
    await fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(ontoggleall).toHaveBeenCalledWith(true);
    expect(oncollectionsall).not.toHaveBeenCalled();
    expect(screen.queryByRole("checkbox", { name: "Collections" })).toBeNull();
  });
});
