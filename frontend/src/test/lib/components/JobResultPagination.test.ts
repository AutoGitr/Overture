import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import JobResultPagination from "../../../lib/components/JobResultPagination.svelte";

interface ResultPage {
  runId: string | null;
  total: number;
  offset: number;
  size: number;
  loading: boolean;
  error: string;
  load: ReturnType<typeof vi.fn<(offset?: number) => Promise<void>>>;
}

function resultPage(overrides: Partial<ResultPage> = {}): ResultPage {
  return {
    runId: "run-1",
    total: 250,
    offset: 100,
    size: 100,
    loading: false,
    error: "",
    load: vi.fn<(offset?: number) => Promise<void>>().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("JobResultPagination", () => {
  it("pages through a finished run's results", async () => {
    const page = resultPage();
    render(JobResultPagination, { page });

    expect(screen.getByText("Results 101-200 of 250")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(page.load.mock.calls).toEqual([[0], [200]]);
  });

  it("stops at either end of the results", () => {
    render(JobResultPagination, { page: resultPage({ offset: 0, total: 40 }) });

    expect(screen.getByText("Results 1-40 of 40")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it.each([
    [{ loading: true }, "Loading results..."],
    [{ total: 0, offset: 0 }, "No results"],
  ])("says when there is nothing to page through (%o)", (overrides, text) => {
    render(JobResultPagination, { page: resultPage(overrides) });

    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("shows only the recent results while the run is going", () => {
    render(JobResultPagination, { page: resultPage(), running: true });

    expect(
      screen.getByText("Showing recent results. All results are available when the job finishes."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  });

  it("retries a page that failed to load", async () => {
    const page = resultPage({ error: "Could not load results. Please retry." });
    render(JobResultPagination, { page });

    expect(screen.getByRole("alert")).toHaveTextContent("Could not load results. Please retry.");
    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(page.load).toHaveBeenCalledWith();
  });

  it("renders nothing before a run has results", () => {
    render(JobResultPagination, { page: resultPage({ runId: null }) });

    expect(screen.queryByLabelText("Result pages")).not.toBeInTheDocument();
  });
});
