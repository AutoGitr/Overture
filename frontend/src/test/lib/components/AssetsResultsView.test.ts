import { render, screen, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import type { BulkArtMatchResult } from "../../../generated/ws";
import AssetsResultsView from "../../../lib/components/AssetsResultsView.svelte";
import { themeJobState } from "../../../lib/stores/bulkJobState.svelte";
import { matchState } from "../../../lib/stores/matchState.svelte";

function match(overrides: Partial<BulkArtMatchResult> = {}): BulkArtMatchResult {
  return {
    title: "Alien",
    art_type: "poster",
    url: "https://images.test/poster.jpg",
    source: "tmdb",
    adopted: false,
    ...overrides,
  };
}

/** The badges of the result row that names *title*. */
function badges(title: string) {
  const row = screen.getByText(title).parentElement!;
  return [...row.querySelectorAll(".badge")].map((badge) => badge.textContent);
}

describe("AssetsResultsView", () => {
  beforeEach(() => {
    matchState.reset();
    themeJobState.reset();
  });

  it("shows nothing before either workflow has run", () => {
    render(AssetsResultsView);

    expect(screen.queryByText("Art")).not.toBeInTheDocument();
    expect(screen.queryByText("Themes")).not.toBeInTheDocument();
  });

  it("describes how each artwork was matched", () => {
    matchState.handleCompleted({
      total: 4,
      done: 4,
      results: [
        match({ title: "Perfect", perfect_match: true, hamming: 0, width: 1000, height: 1500 }),
        match({ title: "Close", hamming: 6, source: "fanart" }),
        match({ title: "From the catalog", source: "OvertureDB", adopted: true }),
      ],
    });

    render(AssetsResultsView);

    expect(screen.getByText("Art")).toBeInTheDocument();
    expect(badges("Perfect")).toEqual(["poster", "Perfect match", "tmdb", "1000x1500"]);
    expect(badges("Close")).toEqual(["poster", "d=6", "fanart"]);
    expect(badges("From the catalog")).toEqual(["poster", "Adopted", "Catalog", "OvertureDB"]);
  });

  it("counts settled downloads once a run has queued any", () => {
    themeJobState.handleStarted({ total: 3 });
    themeJobState.handleProgress({ done: 2, queued: 2, settled: 1, downloaded: 1 });

    render(AssetsResultsView);

    const panel = screen.getByText("Themes").closest<HTMLElement>(".job-panel")!;
    expect(within(panel).getByText("downloads settled:")).toHaveTextContent(
      "downloads settled: 1/2",
    );
    expect(within(panel).getByText("downloaded:")).toHaveTextContent("downloaded: 1");
  });
});
