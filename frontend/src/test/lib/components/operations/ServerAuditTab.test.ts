import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OperationsPopup from "../../../../lib/popups/OperationsPopup.svelte";
import { queryClient } from "../../../../lib/rest/queryClient";
import { serverAuditFixState } from "../../../../lib/stores/serverAuditFixState.svelte";
import { serverAuditState } from "../../../../lib/stores/serverAuditState.svelte";
import { settingsState } from "../../../../lib/stores/settingsState.svelte";
import { uiState } from "../../../../lib/stores/uiState.svelte";
import {
  appSettings,
  mediaServers,
  serverAuditEvent,
  serverAuditFixEvent,
  serverAuditResult,
} from "../../../helpers/fixtures";
import { answerConfirmation } from "../../../helpers/notifications";
import { renderWithQueryClient } from "../../../helpers/render";

const { fixAuditFindings, getFolderRoots, startServerAudit } = vi.hoisted(() => ({
  fixAuditFindings: vi.fn(),
  getFolderRoots: vi.fn(),
  startServerAudit: vi.fn(),
}));
vi.mock("../../../../generated/rest/sdk.gen", () => ({
  fixAuditFindings,
  getFolderRoots,
  startServerAudit,
}));

describe("ServerAuditTab results", () => {
  beforeEach(() => {
    queryClient.clear();
    serverAuditState.reset();
    serverAuditFixState.reset();
    uiState.openOperations("audit");
    getFolderRoots.mockResolvedValue({ data: { movies: ["/movies"], shows: [] } });
  });

  it("chooses collections in the scope, beside the folders", async () => {
    settingsState.load(
      appSettings({ media_servers: mediaServers("plex"), collections_supported: true }),
    );
    startServerAudit.mockResolvedValue({ data: { status: "started" } });
    renderWithQueryClient(OperationsPopup);
    await screen.findByRole("checkbox", { name: "/movies" });
    await fireEvent.click(screen.getByRole("checkbox", { name: "Select all collections" }));
    await fireEvent.click(screen.getByRole("button", { name: "Audit server" }));

    await waitFor(() =>
      expect(startServerAudit).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({ check_collections: true, check_themes: true }),
        }),
      ),
    );
  });

  it("starts a background fix and waits for the server before marking rows fixed", async () => {
    serverAuditState.handleCompleted(
      serverAuditEvent({
        finished_at: "2026-09-05T12:00:00Z",
        results: [
          {
            ...serverAuditResult(),
            art_type: "poster",
            hamming: 5,
            item_id: 1,
            kind: "art",
            server_id: 1,
            refresh_error: "Still differs after refresh: d=5",
            status: "phash_mismatch",
            title: "Movie",
          },
          {
            ...serverAuditResult(),
            art_type: "theme",
            item_id: 1,
            kind: "theme",
            server_id: 1,
            server_item_id: "server-1",
            status: "theme_mismatch",
            theme_id: "theme-1",
            title: "Movie",
          },
        ],
      }),
    );
    fixAuditFindings.mockResolvedValue({ data: { status: "started" } });
    renderWithQueryClient(OperationsPopup);

    await fireEvent.click(await screen.findByRole("button", { name: "Refresh 2 Items" }));
    expect((await answerConfirmation(true)).title).toBe("Delete 1 server theme?");

    // Art and themes are fixed by one request.
    await waitFor(() => expect(fixAuditFindings).toHaveBeenCalledOnce());
    expect(fixAuditFindings).toHaveBeenCalledWith(
      expect.objectContaining({
        body: {
          snapshot_finished_at: "2026-09-05T12:00:00Z",
          targets: [
            { art_type: "poster", collection_id: null, item_id: 1, season_id: null, server_id: 1 },
          ],
          themes: [
            {
              collection_id: null,
              item_id: 1,
              server_id: 1,
              server_item_id: "server-1",
              theme_id: "theme-1",
            },
          ],
        },
      }),
    );
    // Accepted requests fix nothing yet: the rows wait for the server.
    expect(serverAuditState.items.some((result) => result.refreshed)).toBe(false);
    expect(serverAuditState.items[0]?.refresh_error).toBeNull();
    expect(serverAuditFixState.pending).toEqual(
      new Set(["art:1::poster:1", "theme:1:server-1:theme-1:1"]),
    );

    serverAuditFixState.handleStarted(serverAuditFixEvent({ total: 1 }));
    expect(await screen.findByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Refresh/ })).not.toBeInTheDocument();

    serverAuditFixState.handleCompleted(
      serverAuditFixEvent({ done: 1, total: 1, log_targets: { Matched: 1 } }),
    );
    expect(serverAuditFixState.pending.size).toBe(0);
  });

  it("enables Poster, Background and Themes for collections and fixes collection themes without delete confirmation", async () => {
    settingsState.load(
      appSettings({ media_servers: mediaServers("plex"), collections_supported: true }),
    );
    renderWithQueryClient(OperationsPopup);
    await screen.findByRole("checkbox", { name: "/movies" });

    expect(screen.getByRole("checkbox", { name: "Poster" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Background" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Themes" })).toBeDisabled();

    await fireEvent.click(screen.getByRole("checkbox", { name: "Select all collections" }));
    expect(screen.getByRole("checkbox", { name: "Poster" })).not.toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Background" })).not.toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Themes" })).not.toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Season poster" })).toBeDisabled();

    serverAuditState.handleCompleted(
      serverAuditEvent({
        finished_at: "2026-09-05T12:00:00Z",
        results: [
          {
            ...serverAuditResult(),
            art_type: "theme",
            collection_id: 4,
            item_id: null,
            kind: "theme",
            server_id: 1,
            server_item_id: "box",
            status: "theme_server_missing",
            theme_id: "box",
            title: "Saga",
          },
        ],
      }),
    );
    fixAuditFindings.mockResolvedValue({ data: { status: "started" } });

    await fireEvent.click(await screen.findByRole("button", { name: "Refresh 1 Item" }));
    expect(screen.queryByText(/Delete .* server theme/)).not.toBeInTheDocument();

    await waitFor(() => expect(fixAuditFindings).toHaveBeenCalledOnce());
    expect(fixAuditFindings).toHaveBeenCalledWith(
      expect.objectContaining({
        body: {
          snapshot_finished_at: "2026-09-05T12:00:00Z",
          targets: [],
          themes: [
            {
              collection_id: 4,
              item_id: null,
              server_id: 1,
              server_item_id: "box",
              theme_id: "box",
            },
          ],
        },
      }),
    );
    expect(serverAuditFixState.pending).toEqual(new Set(["collection:4:theme:1"]));
  });
});
