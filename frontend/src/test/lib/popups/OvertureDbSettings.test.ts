import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import { getSettingsOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import SettingsPopup from "../../../lib/popups/SettingsPopup.svelte";
import { storePublicDatasetStatus } from "../../../lib/realtime/cache";
import { queryClient } from "../../../lib/rest/queryClient";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import { appSettings, publicDatasetStatus } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

describe("OvertureDB in Settings", () => {
  beforeEach(() => {
    queryClient.clear();
    uiState.openPopupByName("settings");
    const settings = appSettings();
    settingsState.load(settings);
    queryClient.setQueryData(getSettingsOptions().queryKey, settings);
  });

  it("saves the switch apart from the app settings", async () => {
    storePublicDatasetStatus(publicDatasetStatus({ enabled: false }));
    const { calls } = mockFetchRoutes({
      "/api/settings": appSettings(),
      "/api/public-dataset/enabled": publicDatasetStatus({ enabled: true }),
    });
    renderWithQueryClient(SettingsPopup);
    expect(
      screen.getByRole("checkbox", { name: "Browse OvertureDB in the sidebar" }),
    ).toBeDisabled();

    await fireEvent.click(await screen.findByRole("checkbox", { name: "Enable OvertureDB" }));
    expect(
      screen.getByRole("checkbox", { name: "Browse OvertureDB in the sidebar" }),
    ).toBeEnabled();
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(uiState.openPopup).toBeNull());
    const enabled = calls.find((call) => call.url === "/api/public-dataset/enabled");
    expect(JSON.parse(String(enabled?.init.body))).toEqual({ enabled: true });
  });

  it("saves the No theme flag with the app settings and leaves the switch alone", async () => {
    storePublicDatasetStatus(publicDatasetStatus({ enabled: true }));
    const { calls } = mockFetchRoutes({ "/api/settings": appSettings() });
    renderWithQueryClient(SettingsPopup);

    await fireEvent.click(
      await screen.findByRole("checkbox", { name: "Trust OvertureDB's No theme flag" }),
    );
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(uiState.openPopup).toBeNull());
    expect(calls.some((call) => call.url === "/api/public-dataset/enabled")).toBe(false);
    const saved = calls.find((call) => call.url === "/api/settings");
    expect(JSON.parse(String(saved?.init.body))).toMatchObject({ overturedb_no_theme: false });
  });
});
