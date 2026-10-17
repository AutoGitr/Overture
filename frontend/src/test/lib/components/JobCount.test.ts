import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import JobCount from "../../../lib/components/JobCount.svelte";
import { JobLifecycleState } from "../../../lib/stores/jobLifecycleState.svelte";

describe("JobCount", () => {
  it("says the run is planning until its total is fixed", async () => {
    const job = new JobLifecycleState({ failureMessage: "Failed" });
    job.handleStarted({});
    const view = render(JobCount, { job, unit: "items" });

    expect(view.container).toHaveTextContent("Planning...");

    job.handleProgress({ done: 3, total: 10 });
    await view.rerender({ job, unit: "items" });
    expect(view.container).toHaveTextContent("3/10 items");
  });
});
