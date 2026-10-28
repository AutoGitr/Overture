import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Main from "../Main.svelte";
import { queryClient } from "../lib/rest/queryClient";
import { navigate } from "../lib/router/routes";
import { mediaServerState } from "../lib/stores/mediaServerState.svelte";
import { realtimeConnectionState } from "../lib/stores/realtimeConnectionState.svelte";
import { uiState } from "../lib/stores/uiState.svelte";
import { type FetchCall, mockFetchRoutes } from "./helpers/fetch";
import { mediaItem, publicDatasetStatus } from "./helpers/fixtures";
import { renderWithQueryClient } from "./helpers/render";

const { realtimeTransport } = vi.hoisted(() => ({
  realtimeTransport: { connect: vi.fn(), disconnect: vi.fn(), retry: vi.fn() },
}));
vi.mock("../lib/realtime/transport", () => ({ realtimeTransport }));

const alien = mediaItem({ id: 1, title: "Alien", media_type: "movie" });

function libraryItems(call: FetchCall) {
  const movies = new URL(call.url, location.origin).searchParams.get("media_type") === "movie";
  return Response.json({ items: movies ? [alien] : [], total: movies ? 1 : 0 });
}

function backend(overrides: Record<string, unknown> = {}) {
  return mockFetchRoutes({
    "/api/library/items": libraryItems,
    "/api/settings": { workflow: "art" },
    "/api/public-dataset/status": publicDatasetStatus(),
    ...overrides,
  });
}

function notice(title: string) {
  return screen.getByText(title).closest(".notice") as HTMLElement;
}

describe("Main", () => {
  beforeEach(async () => {
    queryClient.clear();
    realtimeConnectionState.reset();
    mediaServerState.store({ state: "reachable", message: "" });
    uiState.closePopup();
    await navigate("/movies", { replace: true });
  });

  it("reveals the app once its first loads settle, live for as long as it is shown", async () => {
    backend();

    const view = renderWithQueryClient(Main, { onLogout: vi.fn() });

    expect(screen.getByRole("status", { name: "Loading Overture" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("status", { name: "Loading Overture" })).toBeNull(),
    );
    expect(screen.getByRole("button", { name: "Select Alien" })).toBeInTheDocument();
    expect(realtimeTransport.connect).toHaveBeenCalledOnce();

    view.unmount();

    expect(realtimeTransport.disconnect).toHaveBeenCalledOnce();
  });

  it("pins a notice while the media server refuses Overture, and checks again", async () => {
    const { calls } = backend({
      "/api/settings/connectivity": { media_server: true, tmdb: true },
    });
    mediaServerState.store({ state: "rejected", message: "check MEDIA_SERVER_API_KEY" });
    renderWithQueryClient(Main, { onLogout: vi.fn() });

    const pinned = notice("The media server refused Overture");
    expect(pinned).toHaveTextContent("check MEDIA_SERVER_API_KEY");
    await fireEvent.click(within(pinned).getByRole("button", { name: "Check again" }));
    await waitFor(() =>
      expect(calls.some((call) => call.url.endsWith("/api/settings/connectivity"))).toBe(true),
    );

    mediaServerState.store({ state: "reachable", message: "" });
    await waitFor(() => expect(screen.queryByText("The media server refused Overture")).toBeNull());
  });

  it("reveals the app even when a first load fails, and offers that load a retry", async () => {
    let available = false;
    backend({
      "/api/settings": () =>
        available
          ? Response.json({ workflow: "art" })
          : Response.json({ detail: "Settings unavailable" }, { status: 404 }),
    });
    renderWithQueryClient(Main, { onLogout: vi.fn() });

    await waitFor(() =>
      expect(screen.queryByRole("status", { name: "Loading Overture" })).toBeNull(),
    );
    const failure = await screen.findByRole("alert");
    expect(failure).toHaveTextContent("Couldn't load Settings");
    expect(failure).toHaveTextContent("Settings unavailable Data is unavailable.");

    available = true;
    await fireEvent.click(within(failure).getByRole("button", { name: "Retry Settings" }));

    await waitFor(() => expect(screen.queryByText("Couldn't load Settings")).toBeNull());
  });

  it("tells an unavailable library apart from an empty one", async () => {
    backend({
      "/api/library/items": () => Response.json({ detail: "Server down" }, { status: 404 }),
    });

    renderWithQueryClient(Main, { onLogout: vi.fn() });

    expect(
      await screen.findByText("Library unavailable. Use Retry in the notification to reconnect."),
    ).toBeInTheDocument();
    expect(screen.getByText("Couldn't load Movies")).toBeInTheDocument();
  });

  it("explains a live connection that is not up and retries it on request", async () => {
    backend();
    renderWithQueryClient(Main, { onLogout: vi.fn() });

    expect(await screen.findByText("Connecting to live updates")).toBeInTheDocument();

    realtimeConnectionState.synced();
    realtimeConnectionState.setPhase("disconnected");
    expect(await screen.findByText("Live connection interrupted")).toBeInTheDocument();

    realtimeConnectionState.error = "Socket refused.";
    await waitFor(() =>
      expect(notice("Live updates failed")).toHaveTextContent(
        "Socket refused. Live data may be out of date.",
      ),
    );
    await fireEvent.click(screen.getByRole("button", { name: "Retry live updates" }));
    expect(realtimeTransport.retry).toHaveBeenCalledOnce();

    realtimeConnectionState.error = "";
    realtimeConnectionState.setPhase("connected");
    await waitFor(() => expect(screen.queryByText(/live/i)).toBeNull());
  });

  it("shows the popup the interface opened", async () => {
    backend();
    renderWithQueryClient(Main, { onLogout: vi.fn() });

    uiState.openPopupByName("filters");

    expect(await screen.findByRole("dialog", { name: "Filters & operations" })).toBeVisible();

    uiState.closePopup();

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
