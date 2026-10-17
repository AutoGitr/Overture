import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OperationsPopup from "../../../../lib/popups/OperationsPopup.svelte";
import { queryClient } from "../../../../lib/rest/queryClient";
import { assetManagerState } from "../../../../lib/stores/assetManagerState.svelte";
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
    renderWithQueryClient(OperationsPopup, { initialTab: "renamer" });

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

  it("selects renamer rows by range and by kind", async () => {
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
    renderWithQueryClient(OperationsPopup, { initialTab: "renamer" });
    const header = await screen.findByRole("checkbox", { name: /4 issues on this page/ });
    const row = (name: string) =>
      screen.getByRole("checkbox", { name: new RegExp(`^${name}[.]jpg`) });

    await fireEvent.click(header);
    expect(header).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Rename 0 Files" })).toBeDisabled();

    await fireEvent.click(row("a"));
    await fireEvent.click(row("c"), { shiftKey: true });
    expect([row("a"), row("b"), row("c")].every((box) => (box as HTMLInputElement).checked)).toBe(
      true,
    );
    expect(row("d")).not.toBeChecked();
    expect((header as HTMLInputElement).indeterminate).toBe(true);
    expect(screen.getByRole("button", { name: "Rename 3 Files" })).toBeEnabled();

    const kinds = screen.getByRole("group", { name: "Select by kind" });
    await fireEvent.click(within(kinds).getByRole("button", { name: /Background/ }));
    expect(header).toBeChecked();
    expect(within(kinds).getByRole("button", { name: /Poster/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await fireEvent.click(within(kinds).getByRole("button", { name: /Poster/ }));
    expect(screen.getByRole("button", { name: "Rename 1 File" })).toBeEnabled();
    expect(row("d")).toBeChecked();
  });
});
