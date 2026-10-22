import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import type { ArtCandidate } from "../../../generated/rest/types.gen";
import ArtSourceSection from "../../../lib/components/ArtSourceSection.svelte";

function candidates(count: number): ArtCandidate[] {
  return Array.from({ length: count }, (_, index) => ({
    art_type: "poster",
    hamming: null,
    iso_639_1: null,
    height: 1500,
    perfect_match: null,
    preview_url: null,
    source: "tmdb",
    title: null,
    url: `https://image.tmdb.org/t/p/original/${index}.jpg`,
    width: 1000,
  }));
}

describe("ArtSourceSection", () => {
  it("shows every candidate at once, each image loading as it scrolls into view", () => {
    render(ArtSourceSection, {
      title: "TMDB",
      arts: candidates(7),
      artType: "poster",
      disabled: false,
      onselect: vi.fn(),
    });

    expect(screen.getByText("7")).toHaveClass("badge-muted");
    const cards = screen.getAllByRole("button", { name: /^Use artwork/ });
    expect(cards).toHaveLength(7);
    // The image is decorative (empty alt), so it is reached through its card.
    expect(cards.map((card) => card.querySelector("img")?.getAttribute("loading"))).toEqual(
      Array(7).fill("lazy"),
    );
    expect(screen.queryByRole("button", { name: /Show/ })).not.toBeInTheDocument();
  });

  it("marks matches for the local file", () => {
    render(ArtSourceSection, {
      title: "MATCHED",
      arts: candidates(4),
      artType: "poster",
      disabled: false,
      onselect: vi.fn(),
      matched: true,
    });
    expect(screen.getByText("4")).toHaveClass("badge-success");
  });
});
