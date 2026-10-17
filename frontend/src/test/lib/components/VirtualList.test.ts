import { render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import { describe, expect, it } from "vitest";
import VirtualListHarness from "../../helpers/VirtualListHarness.svelte";

describe("VirtualList", () => {
  it("clamps a restored scroll offset beyond the current item range", async () => {
    render(VirtualListHarness, { props: { itemCount: 2, scrollOffset: 10_000 } });

    await tick();
    await tick();

    expect(screen.getByText("Row 0")).toBeInTheDocument();
    expect(screen.getByText("Row 1")).toBeInTheDocument();
  });
});
