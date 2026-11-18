import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import InheritedOrder from "../../../lib/components/InheritedOrder.svelte";

const LABELS = { overturedb: "OvertureDB", tmdb: "TMDB", generate: "Generate" };

function boxes() {
  return screen
    .getAllByRole("listitem")
    .map((row) => [
      row.textContent?.trim(),
      (row.querySelector("input") as HTMLInputElement).checked,
    ]);
}

describe("InheritedOrder", () => {
  it("follows Default until customised, starting from the inherited order", async () => {
    const props = $state({
      label: "Automatic art",
      inherits: true,
      value: null as string[] | null,
      onchange: (value: string[] | null) => {
        props.value = value;
      },
      inherited: ["tmdb", "generate"],
      labels: LABELS,
      none: "Off",
    });
    render(InheritedOrder, props);

    const inherit = screen.getByRole("checkbox", { name: "Default (TMDB, then Generate)" });
    expect(inherit).toBeChecked();
    expect(screen.queryByRole("list")).toBeNull();

    await fireEvent.click(inherit);
    expect(props.value).toEqual(["tmdb", "generate"]);
    expect(boxes()).toEqual([
      ["TMDB", true],
      ["Generate", true],
      ["OvertureDB", false],
    ]);
  });

  it("keeps the ticked entries in the order shown", async () => {
    const props = $state({
      label: "Automatic art",
      inherits: false,
      value: ["tmdb"] as string[] | null,
      onchange: (value: string[] | null) => {
        props.value = value;
      },
      labels: LABELS,
      none: "Off",
    });
    render(InheritedOrder, props);

    await fireEvent.click(screen.getByRole("checkbox", { name: "OvertureDB" }));
    expect(props.value).toEqual(["tmdb", "overturedb"]);
    await fireEvent.click(screen.getByRole("checkbox", { name: "TMDB" }));
    expect(props.value).toEqual(["overturedb"]);
    expect(screen.queryByRole("checkbox", { name: /^Default/ })).toBeNull();
  });
});
