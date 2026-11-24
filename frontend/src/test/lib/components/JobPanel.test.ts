import { render } from "@testing-library/svelte";
import { tick } from "svelte";
import { describe, expect, it } from "vitest";
import JobPanel from "../../../lib/components/JobPanel.svelte";
import { JobLogFeed } from "../../../lib/stores/jobLogFeed.svelte";

describe("JobPanel", () => {
  it("spans exactly the grid rows it renders, so no part covers another", async () => {
    const log = new JobLogFeed();
    log.apply({
      run_id: "run",
      log_total: 2,
      log_outcomes: { Added: 2 },
      log_servers: { "1": { Added: 1 }, "2": { Added: 1 } },
    });
    const job = {
      read: 0,
      planning: false,
      done: 1,
      total: 2,
      started_at: "2026-06-02T10:00:00Z",
      finished_at: null,
      schedule: null,
      progress: 50,
      log,
    };

    const { container } = render(JobPanel, { job, unit: "items", stats: [] });
    await tick();

    const panel = container.querySelector("section")!;
    const span = Number(/span (\d+)/.exec(panel.style.gridRow)?.[1]);
    expect(panel.children).toHaveLength(span);
  });
});
