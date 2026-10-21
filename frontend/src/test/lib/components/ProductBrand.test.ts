import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import ProductBrand from "../../../lib/components/ProductBrand.svelte";

describe("ProductBrand", () => {
  it("renders the shared brand text without accented variants or mojibake", () => {
    render(ProductBrand, { props: { as: "h1", size: "lg" } });

    expect(screen.getByRole("heading", { name: "Overture" })).toBeInTheDocument();
    expect(document.body).toHaveTextContent("Overture");
    expect(document.body).not.toHaveTextContent("Over\u00e8ture");
    expect(document.body).not.toHaveTextContent("\u00c3");
  });

  it("uses the shared icon without duplicating the accessible brand name", () => {
    const { container } = render(ProductBrand, { props: { as: "h1", size: "md" } });
    const icon = container.querySelector("img");
    expect(icon).toHaveAttribute("src", "/brand/overture-logo-inline.svg");
    expect(icon).toHaveAttribute("alt", "");
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("heading", { name: "Overture" })).toBeInTheDocument();
  });

  it("renders as a clickable link when href is provided", () => {
    render(ProductBrand, {
      props: {
        as: "h1",
        size: "md",
        href: "/",
        target: "_self",
      },
    });

    expect(screen.getByRole("heading", { name: "Overture" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Overture" });
    expect(link).toHaveAttribute("href", "/");
    expect(link).toHaveAttribute("target", "_self");
  });

  it("renders directly as anchor when as='a'", () => {
    const { container } = render(ProductBrand, {
      props: {
        as: "a",
        size: "md",
        href: "/",
      },
    });

    const link = screen.getByRole("link", { name: "Overture" });
    expect(link).toHaveAttribute("href", "/");
    expect(link).not.toHaveAttribute("target");
    expect(container.querySelector("h1")).toBeNull();
  });
});
