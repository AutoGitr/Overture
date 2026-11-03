import { fireEvent, render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import { describe, expect, it, vi } from "vitest";
import JobLog from "../../../lib/components/JobLog.svelte";
import { JobLogFeed } from "../../../lib/stores/jobLogFeed.svelte";
import { logEntry } from "../../helpers/fixtures";

describe("JobLog", () => {
  it("shows each entry's time, outcome, target and reason apart", async () => {
    const entry = logEntry("Error", "Alien (poster)", "lookup failed");
    const feed = new JobLogFeed();
    feed.apply({ log: entry });

    render(JobLog, { feed });
    await tick();

    const outcome = screen.getByText("Error");
    expect(outcome).toHaveClass("log-outcome", "danger");
    expect(screen.getByText("Alien (poster)")).toHaveClass("log-target");
    expect(screen.getByText("lookup failed")).toHaveClass("log-reason");
    const row = outcome.closest(".job-log-row");
    expect(row).toHaveAttribute("title", "Alien (poster) - lookup failed");
    expect(row?.querySelector("time")).toHaveAttribute("datetime", entry.at);
  });

  it("says so before anything is logged", () => {
    render(JobLog, { feed: new JobLogFeed() });

    expect(screen.getByRole("log")).toHaveTextContent("Nothing logged yet");
  });

  it("offers a retry over the lines when a page fails to load", async () => {
    const feed = new JobLogFeed();
    feed.apply({ log: logEntry("Added", "Alien", "new") });
    feed.error = "Could not load the log. Please retry.";
    const retry = vi.spyOn(feed, "retry");

    render(JobLog, { feed });

    expect(screen.getByRole("alert")).toHaveTextContent("Could not load the log. Please retry.");
    expect(screen.getByText("Alien")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
