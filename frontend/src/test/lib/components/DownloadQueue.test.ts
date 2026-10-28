import { render, screen, within } from "@testing-library/svelte";
import { tick } from "svelte";
import { beforeEach, describe, expect, it } from "vitest";
import type { DownloadJobEvent } from "../../../generated/ws";
import DownloadQueue from "../../../lib/components/DownloadQueue.svelte";
import { downloadState } from "../../../lib/stores/downloadState.svelte";
import { itemDownload } from "../../helpers/fixtures";

/** A running download of *title*'s poster, or of its theme. */
function download(id: string, title: string, jobType: "art" | "theme" = "art"): DownloadJobEvent {
  const event = itemDownload(id, 1);
  const target = {
    target_type: "item",
    source: jobType === "art" ? "TMDB" : "YouTube",
    media_item_id: 1,
    title,
    job_type: jobType,
    art_type: jobType === "art" ? "poster" : null,
    season_id: null,
  } as const;
  return { ...event, job: { ...event.job, target } };
}

function rows(): string[] {
  return within(screen.getByRole("region", { name: "Downloads" }))
    .getAllByText(/.+/, { selector: ".download-title" })
    .map((title) => title.textContent ?? "");
}

describe("DownloadQueue", () => {
  beforeEach(() => {
    downloadState.replaceSnapshot([]);
  });

  it("names where each download comes from after its kind", () => {
    downloadState.replaceSnapshot([download("art", "Alien")]);
    render(DownloadQueue, { lane: "art", label: "Downloads" });
    expect(screen.getByText("TMDB")).toHaveClass("text-muted");
  });

  it("lists the lane's downloads with their kind and step", () => {
    downloadState.replaceSnapshot([
      { ...download("art", "Alien"), stage: "downloading", step: 1, steps: 3, percent: 20 },
      download("theme", "Firefly", "theme"),
    ]);

    render(DownloadQueue, { lane: "art", label: "Downloads" });

    expect(rows()).toEqual(["Alien"]);
    expect(screen.getByText("Poster")).toBeInTheDocument();
    expect(screen.getByText("Downloading 1/3")).toBeInTheDocument();
  });

  it("labels theme downloads apart from art", () => {
    downloadState.replaceSnapshot([download("theme", "Firefly", "theme")]);

    render(DownloadQueue, { lane: "theme", label: "Downloads" });

    expect(screen.getByText("Theme")).toHaveClass("badge");
  });

  it("keeps each reserved row in place between downloads", async () => {
    downloadState.replaceSnapshot([download("first", "Alien"), download("second", "Brazil")]);
    render(DownloadQueue, { lane: "art", label: "Downloads", reserved: 2 });
    expect(rows()).toEqual(["Alien", "Brazil"]);

    downloadState.handleFinished(download("first", "Alien"));
    await tick();
    expect(rows()).toEqual(["Idle", "Brazil"]);

    downloadState.handleStarted(download("third", "Casablanca"));
    await tick();
    expect(rows()).toEqual(["Casablanca", "Brazil"]);
  });

  it("shows nothing while the lane has nothing to show", () => {
    render(DownloadQueue, { lane: "art", label: "Downloads" });

    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });

  it("counts the downloads waiting behind the running ones", () => {
    downloadState.replaceSnapshot([
      download("running", "Alien"),
      ...Array.from({ length: 1000 }, (_, index) => itemDownload(`pending-${index}`, 2, "pending")),
    ]);

    render(DownloadQueue, { lane: "art", label: "Downloads" });

    expect(screen.getByRole("status")).toHaveTextContent("1000 queued");
    expect(rows()).toEqual(["Alien"]);
  });
});
