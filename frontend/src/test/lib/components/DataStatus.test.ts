import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import DataStatus from "../../../lib/components/DataStatus.svelte";
import { ApiError } from "../../../lib/rest/transport";

describe("DataStatus", () => {
  it("distinguishes loading, failure, stale data, and successful completion", async () => {
    const onretry = vi.fn();
    const view = render(DataStatus, { label: "library", loading: true, onretry });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(await screen.findByRole("status")).toHaveTextContent("Loading library");
    await view.rerender({
      label: "library",
      loading: false,
      error: new ApiError("Unavailable", 503),
      onretry,
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Data is unavailable.");
    expect(screen.getByRole("alert")).toHaveTextContent("Unavailable");
    await fireEvent.click(screen.getByRole("button", { name: "Retry library" }));
    expect(onretry).toHaveBeenCalledOnce();
    await view.rerender({
      label: "library",
      hasData: true,
      error: new ApiError("Unavailable", 503),
      onretry,
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Showing last loaded data.");
    await view.rerender({ label: "library", hasData: true, error: null, onretry });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
