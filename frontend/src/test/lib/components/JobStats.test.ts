import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import JobStats, {
  type JobProgressView,
  type JobStat,
} from "../../../lib/components/JobStats.svelte";
import { serverClock } from "../../../lib/realtime/serverClock";

describe("JobStats", () => {
  it("renders progress count and unit", () => {
    const job: JobProgressView = {
      planning: false,
      read: 0,
      done: 15,
      total: 30,
      started_at: "2026-06-02T10:00:00Z",
      finished_at: null,
      schedule: null,
    };
    const stats: JobStat[] = [{ label: "downloaded", value: 5, tone: "success" }];

    render(JobStats, { job, unit: "items", stats });

    expect(screen.getByText("items")).toBeInTheDocument();
    expect(screen.getByText("/30")).toBeInTheDocument();
    expect(screen.getByText("downloaded")).toBeInTheDocument();
    expect(screen.getByText("5")).toHaveClass("text-success");
  });

  it("counts what a planning run has read, until it has read nothing yet", async () => {
    const job: JobProgressView = {
      planning: true,
      read: 1234,
      done: 0,
      total: null,
      started_at: "2026-06-02T10:00:00Z",
      finished_at: null,
      schedule: null,
    };

    const { rerender } = render(JobStats, { job, unit: "items", stats: [] });

    expect(screen.getByText("read").parentElement).toHaveTextContent(/^1234 read$/);
    await rerender({ job: { ...job, read: 0 }, unit: "items", stats: [] });
    expect(screen.getByText("Planning...")).toBeInTheDocument();
  });

  it("names the schedule that started the run", () => {
    const job: JobProgressView = {
      planning: false,
      read: 0,
      done: 1,
      total: 1,
      started_at: "2026-06-02T10:00:00Z",
      finished_at: "2026-06-02T10:00:05Z",
      schedule: "Nightly",
    };

    render(JobStats, { job, unit: "items", stats: [] });

    expect(screen.getByText("scheduled: Nightly")).toBeInTheDocument();
    expect(screen.queryByText("time")).toBeNull();
  });

  it("keeps the counted time when finished_at is behind the live clock", async () => {
    vi.useFakeTimers({ toFake: ["performance"] });
    serverClock.sync("2026-06-02T10:00:10Z");
    const job: JobProgressView = {
      planning: false,
      read: 0,
      done: 10,
      total: 10,
      started_at: "2026-06-02T10:00:00Z",
      finished_at: null,
      schedule: null,
    };

    const { rerender } = render(JobStats, { job, unit: "items", stats: [] });
    expect(screen.getByText("10s")).toBeInTheDocument();

    await rerender({
      job: { ...job, finished_at: "2026-06-02T10:00:08Z" },
      unit: "items",
      stats: [],
    });

    expect(screen.getByText("10s")).toBeInTheDocument();
    expect(screen.queryByText("8s")).not.toBeInTheDocument();
  });
});
