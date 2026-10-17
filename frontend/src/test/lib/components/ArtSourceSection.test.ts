import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ArtCandidate } from "../../../generated/rest/types.gen";
import ArtSourceSection from "../../../lib/components/ArtSourceSection.svelte";
import { settingsState } from "../../../lib/stores/settingsState.svelte";

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
  beforeEach(() => settingsState.load({ initial_results: 2, load_more_step: 3 }));

  it("shows the first results, then more on request, then all", async () => {
    render(ArtSourceSection, {
      title: "TMDB",
      arts: candidates(7),
      artType: "poster",
      disabled: false,
      onselect: vi.fn(),
    });
    expect(screen.getByText("2 / 7")).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: "Show more (5 remaining)" }));
    expect(screen.getByText("5 / 7")).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(screen.getByText("7 / 7")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Show more/ })).not.toBeInTheDocument();
  });

  it("shows every match at once", () => {
    render(ArtSourceSection, {
      title: "MATCHED",
      arts: candidates(4),
      artType: "poster",
      disabled: false,
      onselect: vi.fn(),
      paged: false,
      matched: true,
    });
    expect(screen.getByText("4")).toHaveClass("badge-success");
    expect(screen.queryByRole("button", { name: /Show/ })).not.toBeInTheDocument();
  });
});
