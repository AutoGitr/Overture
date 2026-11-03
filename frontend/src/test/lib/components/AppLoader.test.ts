import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import AppLoader from "../../../lib/components/AppLoader.svelte";

describe("AppLoader", () => {
  it("renders the product mark and spinner without requiring props", () => {
    render(AppLoader);

    expect(screen.getByText("Overture")).toBeInTheDocument();
    expect(document.body).toHaveTextContent("Overture");
    expect(document.querySelector(".loader-spinner")).toBeInTheDocument();
  });
});
