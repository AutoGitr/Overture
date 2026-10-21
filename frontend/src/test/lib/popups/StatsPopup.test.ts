import { fireEvent, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Coverage, StatsResponse } from "../../../generated/rest/types.gen";
import StatsPopup from "../../../lib/popups/StatsPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { ApiError } from "../../../lib/rest/transport";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { renderWithQueryClient } from "../../helpers/render";

const { getStats } = vi.hoisted(() => ({
  getStats: vi.fn(),
}));

vi.mock("../../../generated/rest/sdk.gen", () => ({
  getStats,
}));

/** Coverage as the backend reports it, its shares worked out from the counts. */
function coverage(total: number, local: number, matched: number, bytes: number): Coverage {
  const share = (part: number) => (total ? Math.round((part / total) * 1000) / 10 : 0);
  return {
    total,
    local_files: local,
    matched_files: matched,
    total_size_bytes: bytes,
    local_percentage: share(local),
    matched_percentage: share(matched),
    avg_size_bytes: local ? Math.round(bytes / local) : 0,
  };
}

const mockStats: StatsResponse = {
  library: {
    total_movies: 120,
    monitored_movies: 100,
    unmonitored_movies: 20,
    total_shows: 45,
    monitored_shows: 40,
    unmonitored_shows: 5,
    total_seasons: 180,
    seasons_with_episodes: 160,
    total_collections: 12,
    monitored_collections: 10,
  },
  art: {
    poster: coverage(165, 150, 140, 150000000),
    poster_movies: coverage(120, 110, 105, 110000000),
    poster_shows: coverage(45, 40, 35, 40000000),
    background: coverage(165, 140, 130, 280000000),
    background_movies: coverage(120, 105, 98, 210000000),
    background_shows: coverage(45, 35, 32, 70000000),
    season_poster: coverage(180, 160, 150, 80000000),
    overall: coverage(510, 450, 420, 510000000),
  },
  themes: {
    movies: coverage(120, 60, 55, 120000000),
    shows: coverage(45, 30, 28, 60000000),
    collections: coverage(12, 8, 7, 0),
    overall: coverage(177, 98, 90, 180000000),
  },
  database: {
    file_size_bytes: 15728640,
    wal_size_bytes: 4194304,
    total_size_bytes: 19922944,
    page_size: 4096,
    page_count: 3840,
    freelist_count: 120,
    free_size_bytes: 491520,
    tables: [
      { table_name: "media_items", description: "Movies and TV shows", row_count: 165 },
      { table_name: "seasons", description: "Show seasons", row_count: 180 },
      { table_name: "media_item_art", description: "Poster and background slots", row_count: 330 },
      { table_name: "season_art", description: "Season poster slots", row_count: 180 },
      {
        table_name: "collection_themes",
        description: "Collection theme assignments",
        row_count: 12,
      },
    ],
  },
  backups: {
    total_backups: 3,
    total_size_bytes: 35000000,
    latest_backup_at: "2026-09-14T03:00:00Z",
  },
  storage: {
    artwork_size_bytes: 510000000,
    themes_size_bytes: 180000000,
    database_size_bytes: 19922944,
    backups_size_bytes: 35000000,
    total_footprint_bytes: 744922944,
  },
  generated_at: "2026-09-15T12:00:00Z",
};

describe("StatsPopup", () => {
  beforeEach(() => {
    queryClient.clear();
    uiState.openPopupByName("stats");
    getStats.mockResolvedValue({ data: mockStats });
  });

  it("renders statistics popup with overview tab by default", async () => {
    renderWithQueryClient(StatsPopup);

    expect(await screen.findByRole("heading", { name: "Statistics" })).toBeInTheDocument();
    expect(await screen.findByText("Total Footprint")).toBeInTheDocument();
    expect(screen.getByText("Storage Distribution")).toBeInTheDocument();
    expect(screen.getByText("Library Breakdown")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument(); // total movies
    expect(screen.getByText("45")).toBeInTheDocument(); // total shows
  });

  it("switches to artwork tab and displays art category breakdowns", async () => {
    renderWithQueryClient(StatsPopup);

    await fireEvent.click(await screen.findByRole("tab", { name: "Artwork" }));

    expect(screen.getByText("Overall Artwork Coverage")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Posters" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Backgrounds" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Season Posters" })).toBeInTheDocument();
    expect(screen.getByText("150 / 165")).toBeInTheDocument(); // posters configured
  });

  it("switches to themes tab and displays theme category breakdowns", async () => {
    renderWithQueryClient(StatsPopup);

    await fireEvent.click(await screen.findByRole("tab", { name: "Themes" }));

    expect(screen.getByText("Overall Theme Audio Coverage")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Movie Themes" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "TV Show Themes" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Collection Themes" })).toBeInTheDocument();
    expect(screen.getByText("60 / 120")).toBeInTheDocument(); // movie themes configured
  });

  it("marks collections unavailable when the media server could not list them", async () => {
    getStats.mockResolvedValue({
      data: {
        ...mockStats,
        library: { ...mockStats.library, total_collections: null, monitored_collections: null },
        themes: { ...mockStats.themes, collections: null },
      },
    });
    renderWithQueryClient(StatsPopup);

    expect(await screen.findByText("Unavailable from media server")).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("tab", { name: "Themes" }));

    expect(screen.getByRole("heading", { name: "Collection Themes" })).toBeInTheDocument();
    expect(
      screen.getByText("Unavailable: the media server could not list its collections."),
    ).toBeInTheDocument();
  });

  it("switches to database tab and displays engine metrics and tables", async () => {
    renderWithQueryClient(StatsPopup);

    await fireEvent.click(await screen.findByRole("tab", { name: "Database" }));

    expect(screen.getByText("SQLite Engine & Storage")).toBeInTheDocument();
    expect(screen.getByText("Database Tables (5)")).toBeInTheDocument();
    expect(screen.getByText("media_items")).toBeInTheDocument();
    expect(screen.getByText("seasons")).toBeInTheDocument();
    expect(screen.getByText("media_item_art")).toBeInTheDocument();
    expect(screen.getByText("Poster and background slots")).toBeInTheDocument();
    expect(screen.getByText("Backups")).toBeInTheDocument();
  });

  it("handles loading error and allows retry", async () => {
    getStats.mockRejectedValue(new ApiError("Stats unavailable", 403, "stats-error"));
    renderWithQueryClient(StatsPopup);

    expect(await screen.findByRole("alert")).toHaveTextContent("stats-error");

    getStats.mockResolvedValue({ data: mockStats });
    await fireEvent.click(screen.getByRole("button", { name: "Retry statistics" }));

    expect(await screen.findByText("Total Footprint")).toBeInTheDocument();
  });

  it("closes popup when close button is clicked", async () => {
    renderWithQueryClient(StatsPopup);

    await fireEvent.click(await screen.findByRole("button", { name: "Close" }));

    expect(uiState.openPopup).toBeNull();
  });
});
