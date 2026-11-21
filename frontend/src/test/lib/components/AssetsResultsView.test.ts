import { render, screen, within } from "@testing-library/svelte";
import { tick } from "svelte";
import { beforeEach, describe, expect, it } from "vitest";
import AssetsResultsView from "../../../lib/components/AssetsResultsView.svelte";
import { matchState, themeJobState } from "../../../lib/stores/bulkJobState.svelte";
import { downloadState } from "../../../lib/stores/downloadState.svelte";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import {
  appSettings,
  bulkArtEvent,
  bulkThemeEvent,
  itemDownload,
  logEntry,
} from "../../helpers/fixtures";

function panel(name: string): HTMLElement {
  return screen.getByRole("region", { name });
}

describe("AssetsResultsView", () => {
  beforeEach(() => {
    matchState.reset();
    themeJobState.reset();
    settingsState.reset();
    downloadState.replaceSnapshot([]);
  });

  it("shows nothing before either workflow has run", () => {
    render(AssetsResultsView);

    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });

  it("gives each workflow that ran its own panel and log", () => {
    matchState.handleStarted(bulkArtEvent({ run_id: "art", log_total: 0 }));
    matchState.handleProgress(
      bulkArtEvent({
        run_id: "art",
        log_total: 1,
        log: logEntry("Queued", "Alien (poster)", "d=3 from tmdb; 1000x1500"),
      }),
    );

    render(AssetsResultsView);

    expect(within(panel("Art")).getByRole("log")).toHaveTextContent("d=3 from tmdb; 1000x1500");
    expect(screen.queryByRole("region", { name: "Themes" })).not.toBeInTheDocument();
  });

  it("counts only the queued downloads that have not settled", () => {
    themeJobState.handleStarted(bulkThemeEvent({ total: 3 }));
    themeJobState.handleProgress(
      bulkThemeEvent({ done: 2, settled: 1, log_targets: { Queued: 2, Downloaded: 1 } }),
    );

    render(AssetsResultsView);

    const themes = panel("Themes");
    expect(within(themes).getByTitle("Downloads waiting or still running")).toHaveTextContent(
      /^queued\s*1$/,
    );
    expect(within(themes).getByTitle("Files downloaded and saved to disk")).toHaveTextContent(
      /^downloaded\s*1$/,
    );
    expect(
      within(themes).getByTitle("Existing file kept and linked to an art URL or YouTube ID"),
    ).toHaveTextContent(/^adopted\s*0$/);
  });

  it("holds a row per lane worker from a run's first download until it ends", async () => {
    settingsState.load(appSettings({ art_download_workers: 2 }));
    matchState.handleStarted(bulkArtEvent({ total: 3 }));
    themeJobState.handleStarted(bulkThemeEvent({ total: 1 }));
    render(AssetsResultsView);
    expect(screen.queryByText("Idle")).not.toBeInTheDocument();

    matchState.handleProgress(bulkArtEvent({ done: 3, settled: 0, log_targets: { Queued: 3 } }));
    themeJobState.handleProgress(
      bulkThemeEvent({ done: 1, settled: 0, log_targets: { Queued: 1 } }),
    );
    downloadState.handleStarted(itemDownload("art-1", 1));
    await tick();
    expect(within(panel("Art")).getAllByText("Idle")).toHaveLength(1);
    expect(within(panel("Themes")).getAllByText("Idle")).toHaveLength(1);

    matchState.handleCompleted(bulkArtEvent({ done: 3, settled: 2, log_targets: { Queued: 3 } }));
    themeJobState.handleCompleted(
      bulkThemeEvent({ done: 1, settled: 1, log_targets: { Queued: 1 } }),
    );
    await tick();
    expect(screen.queryByText("Idle")).not.toBeInTheDocument();
    expect(within(panel("Art")).getByText("Alien")).toBeInTheDocument();
  });
});
