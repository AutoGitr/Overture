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

  it("fills two rows of its panel, filtering by server only across several", async () => {
    const feed = new JobLogFeed();
    const event = {
      run_id: "run",
      log_total: 3,
      log_outcomes: { Added: 2, Started: 1 },
      log_servers: { "1": { Added: 1 } },
    } as const;
    feed.apply(event);

    const { container } = render(JobLog, { feed });
    await tick();

    // JobPanel spans a fixed number of grid rows, two of them this log's.
    expect(container.children).toHaveLength(2);
    expect(screen.getByRole("group", { name: "Show log lines by outcome" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Show log lines by media server" })).toBeNull();

    feed.apply({ ...event, log_servers: { "1": { Added: 1 }, "2": { Added: 1 } } });
    await tick();

    expect(container.children).toHaveLength(2);
    expect(
      screen.getByRole("group", { name: "Show log lines by media server" }),
    ).toBeInTheDocument();
  });
});
