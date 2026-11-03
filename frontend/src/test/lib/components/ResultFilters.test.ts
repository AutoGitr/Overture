import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import ResultFilters from "../../../lib/components/ResultFilters.svelte";

describe("ResultFilters", () => {
  it("takes no room until there is a first result", () => {
    const { container } = render(ResultFilters, {
      groups: [],
      label: "Outcomes",
      ontoggle: vi.fn(),
    });
    expect(container.children).toHaveLength(0);
    expect(screen.queryByRole("group", { name: "Outcomes" })).toBeNull();
  });
});
