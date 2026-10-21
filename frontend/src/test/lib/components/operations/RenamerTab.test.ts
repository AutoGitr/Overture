import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OperationsPopup from "../../../../lib/popups/OperationsPopup.svelte";
import { queryClient } from "../../../../lib/rest/queryClient";
import { assetManagerState } from "../../../../lib/stores/assetManagerState.svelte";
import { uiState } from "../../../../lib/stores/uiState.svelte";
import { renderWithQueryClient } from "../../../helpers/render";

const { getFolderRoots, renameAssets } = vi.hoisted(() => ({
  getFolderRoots: vi.fn(),
  renameAssets: vi.fn(),
}));
vi.mock("../../../../generated/rest/sdk.gen", () => ({ getFolderRoots, renameAssets }));

describe("RenamerTab results", () => {
  beforeEach(() => {
    queryClient.clear();
    assetManagerState.reset();
    uiState.openOperations("renamer");
    getFolderRoots.mockResolvedValue({ data: { movies: ["/movies"], shows: [] } });
  });

  it("applies successful asset renames to the completed scan", async () => {
    assetManagerState.handleCompleted({
      finished_at: "2026-09-05T12:00:00Z",
      issues: [
        {
          conflict: false,
          current_filename: "movie.jpg",
          current_path: "/movies/Movie/movie.jpg",
          folder: "/movies/Movie",
          height: 1500,
          suggested_filename: "poster.jpg",
          potential_false_positive: false,
          suggested_path: "/movies/Movie/poster.jpg",
          type: "poster",
          width: 1000,
        },
      ],
    });
    renameAssets.mockResolvedValue({
      data: {
        results: [{ current_path: "/movies/Movie/movie.jpg", status: "renamed" }],
      },
    });
    renderWithQueryClient(OperationsPopup);

    await fireEvent.click(await screen.findByRole("button", { name: "Rename 1 File" }));

    await waitFor(() => expect(assetManagerState.items[0]?.renamed).toBe(true));
    expect(renameAssets).toHaveBeenCalledWith(
      expect.objectContaining({
        body: {
          renames: [
            {
              current_path: "/movies/Movie/movie.jpg",
              suggested_path: "/movies/Movie/poster.jpg",
            },
          ],
          snapshot_finished_at: "2026-09-05T12:00:00Z",
        },
      }),
    );
  });

  it("selects renamer rows by range, and acts only on the kinds shown", async () => {
    const issue = {
      conflict: false,
      folder: "/movies/Movie",
      height: 1500,
      suggested_filename: "poster.jpg",
      potential_false_positive: false,
      type: "poster",
      width: 1000,
    };
    assetManagerState.handleCompleted({
      finished_at: "2026-09-05T12:00:00Z",
      issues: ["a", "b", "c", "d"].map((name, index) => ({
        ...issue,
        current_filename: `${name}.jpg`,
        current_path: `/movies/Movie/${name}.jpg`,
        suggested_path: `/movies/Movie/${name}-poster.jpg`,
        type: index === 3 ? "background" : "poster",
      })),
    });
    renderWithQueryClient(OperationsPopup);
    const header = await screen.findByRole("checkbox", { name: "Select every shown issues" });
    const row = (name: string) =>
      screen.getByRole("checkbox", { name: new RegExp(`^${name}[.]jpg`) });

    await fireEvent.click(header);
    expect(header).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Rename 0 Files" })).toBeDisabled();

    await fireEvent.click(row("a"));
    await fireEvent.click(row("c"), { shiftKey: true });
    for (const box of [row("a"), row("b"), row("c")]) expect(box).toBeChecked();
    expect(row("d")).not.toBeChecked();
    expect(header).toBePartiallyChecked();
    expect(screen.getByRole("button", { name: "Rename 3 Files" })).toBeEnabled();

    const kinds = screen.getByRole("group", { name: "Show issues by kind" });
    const poster = within(kinds).getByRole("button", { name: /Poster/ });
    expect(poster).toHaveAttribute("aria-pressed", "true");
    await fireEvent.click(poster);
    expect(poster).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("checkbox", { name: /^a[.]jpg/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rename 0 Files" })).toBeDisabled();
    expect(screen.getByText(/3 more checked but hidden/)).toBeVisible();
    await fireEvent.click(header);
    expect(row("d")).toBeChecked();
    expect(screen.getByRole("button", { name: "Rename 1 File" })).toBeEnabled();

    await fireEvent.click(poster);
    expect(screen.getByRole("button", { name: "Rename 4 Files" })).toBeEnabled();
  });
});
