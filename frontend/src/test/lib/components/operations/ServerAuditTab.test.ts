import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OperationsPopup from "../../../../lib/popups/OperationsPopup.svelte";
import { queryClient } from "../../../../lib/rest/queryClient";
import { serverAuditFixState } from "../../../../lib/stores/serverAuditFixState.svelte";
import { serverAuditState } from "../../../../lib/stores/serverAuditState.svelte";
import { answerConfirmation } from "../../../helpers/notifications";
import { renderWithQueryClient } from "../../../helpers/render";

const { fixAuditFindings, getFolderRoots } = vi.hoisted(() => ({
  fixAuditFindings: vi.fn(),
  getFolderRoots: vi.fn(),
}));
vi.mock("../../../../generated/rest/sdk.gen", () => ({ fixAuditFindings, getFolderRoots }));

describe("ServerAuditTab results", () => {
  beforeEach(() => {
    queryClient.clear();
    serverAuditState.reset();
    serverAuditFixState.reset();
    getFolderRoots.mockResolvedValue({ data: { movies: ["/movies"], shows: [] } });
  });

  it("starts a background fix and waits for the server before marking rows fixed", async () => {
    serverAuditState.handleCompleted({
      finished_at: "2026-09-05T12:00:00Z",
      results: [
        {
          art_type: "poster",
          hamming: 5,
          item_id: 1,
          kind: "art",
          refresh_error: "Still differs after refresh: d=5",
          status: "phash_mismatch",
          title: "Movie",
        },
        {
          art_type: "theme",
          item_id: 1,
          kind: "theme",
          server_item_id: "server-1",
          status: "theme_mismatch",
          theme_id: "theme-1",
          title: "Movie",
        },
      ],
    });
    fixAuditFindings.mockResolvedValue({ data: { status: "started" } });
    renderWithQueryClient(OperationsPopup, { initialTab: "audit" });

    await fireEvent.click(await screen.findByRole("button", { name: "Refresh 2 Items" }));
    expect((await answerConfirmation(true)).title).toBe("Delete 1 server theme?");

    // Art and themes are fixed by one request.
    await waitFor(() => expect(fixAuditFindings).toHaveBeenCalledOnce());
    expect(fixAuditFindings).toHaveBeenCalledWith(
      expect.objectContaining({
        body: {
          snapshot_finished_at: "2026-09-05T12:00:00Z",
          targets: [{ art_type: "poster", item_id: 1, season_id: undefined }],
          themes: [{ item_id: 1, server_item_id: "server-1", theme_id: "theme-1" }],
        },
      }),
    );
    // Accepted requests fix nothing yet: the rows wait for the server.
    expect(serverAuditState.items.some((result) => result.refreshed)).toBe(false);
    expect(serverAuditState.items[0]?.refresh_error).toBeNull();
    expect(serverAuditFixState.pending).toEqual(
      new Set(["art:1::poster", "theme:1:server-1:theme-1"]),
    );

    serverAuditFixState.handleStarted({ total: 1 });
    expect(await screen.findByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Refresh/ })).not.toBeInTheDocument();

    serverAuditFixState.handleCompleted({ done: 1, total: 1, verified: 1 });
    expect(serverAuditFixState.pending.size).toBe(0);
  });
});
