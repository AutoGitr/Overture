import { render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import { describe, expect, it } from "vitest";
import JobLog from "../../../lib/components/JobLog.svelte";
import { logEntry } from "../../helpers/fixtures";

describe("JobLog", () => {
  it("shows each entry's time, outcome, target and reason apart", async () => {
    const entry = logEntry("Error", "Alien (poster)", "lookup failed");

    render(JobLog, { entries: [entry] });
    await tick();

    const outcome = screen.getByText("Error");
    expect(outcome).toHaveClass("log-outcome", "danger");
    expect(screen.getByText("Alien (poster)")).toHaveClass("log-target");
    expect(screen.getByText("lookup failed")).toHaveClass("log-reason");
    const row = outcome.closest(".job-log-row");
    expect(row).toHaveAttribute("title", "Alien (poster) - lookup failed");
    expect(row?.querySelector("time")).toHaveAttribute("datetime", entry.at);
  });
});
