import { appSettings } from "../../helpers/fixtures";
import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getSettingsOptions,
  listItemsOptions,
} from "../../../generated/rest/@tanstack/svelte-query.gen";
import SettingsPopup from "../../../lib/popups/SettingsPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { ApiError } from "../../../lib/rest/transport";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { renderWithQueryClient } from "../../helpers/render";

const updateSettings = vi.hoisted(() => vi.fn());
const getSettings = vi.hoisted(() => vi.fn());

vi.mock("../../../generated/rest/sdk.gen", () => ({ updateSettings, getSettings }));

function storedSettings() {
  return {
    ...settingsState.toUpdatePayload(),
    media_server: "plex" as const,
    tmdb_configured: false,
    art_download_workers: 1,
    theme_download_workers: 1,
    updated_at: null,
  };
}

describe("SettingsPopup", () => {
  beforeEach(() => {
    queryClient.clear();
    uiState.openPopupByName("settings");
    settingsState.load(
      appSettings({
        workflow: "art",
        auto_match_art: true,
        min_duration_seconds: 30,
        max_duration_seconds: 300,
        aspect_ratio_tolerance: "strict",
      }),
    );
    queryClient.setQueryData(getSettingsOptions().queryKey, storedSettings());
    getSettings.mockResolvedValue({ data: settingsState.toUpdatePayload() });
  });

  it("closes without saving when cancel is clicked", async () => {
    updateSettings.mockResolvedValue({ data: {} });
    renderWithQueryClient(SettingsPopup);

    await fireEvent.change(screen.getByRole("combobox", { name: "Workflow" }), {
      target: { value: "themes" },
    });
    await fireEvent.click(screen.getByText("Cancel"));

    expect(settingsState.current.workflow).toBe("art");
    expect(uiState.openPopup).toBeNull();
    expect(updateSettings).not.toHaveBeenCalled();
  });

  it("names the media server as users know it", async () => {
    renderWithQueryClient(SettingsPopup);

    expect(await screen.findByLabelText("Skip TMDB images from Plex")).toBeInTheDocument();
    expect(screen.getByLabelText("Disable fetching art from Plex")).toBeInTheDocument();
  });

  it("does not expose the removed resolution pre-filter setting", () => {
    renderWithQueryClient(SettingsPopup);

    expect(screen.queryByText("Disable resolution pre-filtering")).not.toBeInTheDocument();
  });

  it("saves the workflow and completion policy independently of navigation", async () => {
    updateSettings.mockResolvedValue({
      data: {
        workflow: "art_and_themes",
        auto_unmonitor: "art_and_theme",
        auto_advance: false,
      },
    });
    renderWithQueryClient(SettingsPopup);
    await fireEvent.change(screen.getByLabelText("Workflow"), {
      target: { value: "art_and_themes" },
    });
    await fireEvent.change(screen.getByLabelText("Auto-unmonitor"), {
      target: { value: "art_and_theme" },
    });
    expect(screen.getByLabelText("Skip completed slots and items")).toBeDisabled();
    expect(screen.queryByLabelText("Default Tab")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Auto-advance delay")).not.toBeInTheDocument();
    await fireEvent.click(screen.getByText("Save"));
    await waitFor(() => {
      expect(updateSettings).toHaveBeenCalledWith({
        body: expect.objectContaining({
          workflow: "art_and_themes",
          auto_unmonitor: "art_and_theme",
          auto_advance: false,
        }),
        throwOnError: true,
      });
      expect(settingsState.current.auto_unmonitor).toBe("art_and_theme");
    });
  });

  it("saves editable settings and applies the returned server settings", async () => {
    updateSettings.mockResolvedValue({
      data: {
        workflow: "themes",
        auto_match_art: false,
      },
    });
    renderWithQueryClient(SettingsPopup);

    const defaultTabSelect = screen.getByRole("combobox", { name: "Workflow" });
    expect(defaultTabSelect).toBeInstanceOf(HTMLSelectElement);
    await fireEvent.change(defaultTabSelect, {
      target: { value: "themes" },
    });
    await fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(updateSettings).toHaveBeenCalledWith({
        body: expect.objectContaining({
          workflow: "themes",
        }),
        throwOnError: true,
      });
      expect(settingsState.current.workflow).toBe("themes");
      expect(uiState.openPopup).toBeNull();
    });
  });

  it("saves theme loudness normalization, on by default", async () => {
    updateSettings.mockResolvedValue({ data: { normalize_theme_loudness: false } });
    renderWithQueryClient(SettingsPopup);

    const normalize = screen.getByLabelText("Normalize theme loudness");
    expect(normalize).toBeChecked();
    await fireEvent.click(normalize);
    await fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(updateSettings).toHaveBeenCalledWith({
        body: expect.objectContaining({ normalize_theme_loudness: false }),
        throwOnError: true,
      });
      expect(settingsState.current.normalize_theme_loudness).toBe(false);
    });
  });

  it.each([
    ["lenient", true],
    ["strict", false],
  ] as const)(
    "refreshes library items only when the aspect ratio tolerance changes (%s)",
    async (tolerance, refreshed) => {
      const itemsKey = listItemsOptions({ query: { media_type: "movie" } }).queryKey;
      queryClient.setQueryData(itemsKey, { items: [], total: 0 });
      updateSettings.mockResolvedValue({ data: { aspect_ratio_tolerance: tolerance } });
      renderWithQueryClient(SettingsPopup);

      await fireEvent.change(screen.getByLabelText("Aspect ratio control"), {
        target: { value: tolerance },
      });
      await fireEvent.click(screen.getByText("Save"));

      await waitFor(() => expect(uiState.openPopup).toBeNull());
      expect(queryClient.getQueryState(itemsKey)?.isInvalidated).toBe(refreshed);
    },
  );

  it("redacts sensitive save errors in the visible footer", async () => {
    updateSettings.mockRejectedValue(new Error("token=secret"));
    renderWithQueryClient(SettingsPopup);

    await fireEvent.click(screen.getByText("Save"));

    expect(await screen.findByText("token=[REDACTED]")).toBeInTheDocument();
  });

  it("persists and applies appearance only when settings are saved", async () => {
    updateSettings.mockResolvedValue({ data: { workflow: "art" } });
    renderWithQueryClient(SettingsPopup);
    await fireEvent.change(screen.getByRole("combobox", { name: "Theme Mode" }), {
      target: { value: "light" },
    });
    expect(localStorage.getItem("theme")).toBeNull();

    await fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(localStorage.getItem("theme")).toBe(JSON.stringify("light"));
      expect(document.documentElement).toHaveAttribute("data-theme", "light");
    });
  });

  it("persists and applies custom hex colors when edited and saved", async () => {
    updateSettings.mockResolvedValue({ data: { workflow: "art" } });
    renderWithQueryClient(SettingsPopup);

    const accentInput = screen.getByLabelText("Accent Color hex value");
    const bgInput = screen.getByLabelText("Background Color hex value");

    await fireEvent.focus(accentInput);
    await fireEvent.input(accentInput, { target: { value: "ff0055" } });
    await fireEvent.blur(accentInput);

    await fireEvent.focus(bgInput);
    await fireEvent.input(bgInput, { target: { value: "#112233" } });
    await fireEvent.blur(bgInput);

    await fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(localStorage.getItem("accentColor")).toBe(JSON.stringify("#ff0055"));
      expect(localStorage.getItem("bgColor")).toBe(JSON.stringify("#112233"));
      expect(document.documentElement.style.getPropertyValue("--accent")).toBe("#ff0055");
      expect(document.documentElement.style.getPropertyValue("--bg-root")).toBe("#112233");
    });
  });

  it("prevents saving defaults when settings are unavailable and initializes after retry", async () => {
    queryClient.clear();
    getSettings.mockRejectedValue(new ApiError("Settings unavailable", 503));
    renderWithQueryClient(SettingsPopup);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(await screen.findByRole("alert", {}, { timeout: 5000 })).toHaveTextContent(
      "Settings unavailable",
    );
    expect(screen.getByLabelText("Workflow")).toBeDisabled();
    getSettings.mockResolvedValue({
      data: { ...settingsState.toUpdatePayload(), workflow: "themes" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Retry settings" }));
    await waitFor(() => expect(screen.getByLabelText("Workflow")).toHaveValue("themes"));
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    expect(updateSettings).not.toHaveBeenCalled();
  });

  it("keeps an in-progress settings draft when a background refresh arrives", async () => {
    renderWithQueryClient(SettingsPopup);
    await fireEvent.change(screen.getByLabelText("Workflow"), { target: { value: "themes" } });
    queryClient.setQueryData(getSettingsOptions().queryKey, {
      ...storedSettings(),
      min_duration_seconds: 45,
    });
    await waitFor(() => expect(screen.getByLabelText("Workflow")).toHaveValue("themes"));
    expect(screen.getByLabelText("Min Theme Duration (seconds)")).toHaveValue(30);
  });
});
