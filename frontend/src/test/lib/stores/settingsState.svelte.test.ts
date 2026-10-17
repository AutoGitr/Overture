import { afterEach, describe, expect, it } from "vitest";
import { DEFAULT_APP_SETTINGS } from "../../../generated/settings";
import { settingsState } from "../../../lib/stores/settingsState.svelte";

describe("settingsState", () => {
  afterEach(() => {
    settingsState.load({});
  });

  it("starts from the backend's generated defaults", () => {
    expect(settingsState.toUpdatePayload()).toEqual(DEFAULT_APP_SETTINGS);
    expect(settingsState.current.auto_match_art).toBe(false);
    expect(settingsState.current.auto_advance_skip_completed).toBe(true);
  });

  it("replaces every setting on load, defaulting the ones left out", () => {
    settingsState.load({ workflow: "themes", auto_match_art: true });
    settingsState.load({ workflow: "art_and_themes", media_server: "jellyfin" });

    expect(settingsState.current.workflow).toBe("art_and_themes");
    expect(settingsState.current.auto_match_art).toBe(DEFAULT_APP_SETTINGS.auto_match_art);
    expect(settingsState.media_server_name).toBe("Jellyfin");
    expect(settingsState.initial_tab).toBe("art");
  });

  it("leaves read-only environment fields out of the update payload", () => {
    settingsState.load({
      workflow: "themes",
      media_server: "plex",
      tmdb_configured: true,
      skip_media_server_tmdb_urls: true,
    });

    const payload = settingsState.toUpdatePayload();

    expect(payload).toMatchObject({ workflow: "themes", skip_media_server_tmdb_urls: true });
    expect(settingsState.current.media_server).toBe("plex");
    expect(payload).not.toHaveProperty("media_server");
    expect(payload).not.toHaveProperty("tmdb_configured");
  });
});
