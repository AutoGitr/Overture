import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Checklist from "../../../lib/components/Checklist.svelte";

describe("Checklist", () => {
  it("names the list beside its select-all control and toggles options by group", async () => {
    const ontoggle = vi.fn();
    const ontoggleall = vi.fn();
    render(Checklist, {
      label: "Libraries",
      groups: [
        { key: "movie", label: "Movies", options: [{ id: "1", label: "Films", checked: true }] },
        { key: "show", label: "Shows", options: [] },
      ],
      allSelected: false,
      ontoggle,
      ontoggleall,
    });

    expect(screen.getByText("Libraries")).toBeInTheDocument();
    expect(screen.queryByText("Shows")).toBeNull();
    expect(screen.getByRole("checkbox", { name: "Films" })).toBeChecked();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Films" }));
    expect(ontoggle).toHaveBeenCalledWith("movie", "1");
    await fireEvent.click(screen.getByRole("checkbox", { name: "Select All" }));
    expect(ontoggleall).toHaveBeenCalledWith(true);
  });
});
