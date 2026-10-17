import { getSettingsOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
import type { AppSettingsRead } from "../../generated/rest/types.gen";
import { followQuery } from "../rest/queryClient";
import { DEFAULT_APP_SETTINGS, SERVER_DISPLAY_NAMES } from "../../generated/settings";
import { loadAppearancePreferences } from "../utils/appearance";

/** What the dashboard assumes until the saved settings arrive. */
const INITIAL_SETTINGS: AppSettingsRead = {
  ...DEFAULT_APP_SETTINGS,
  media_server: null,
  tmdb_configured: false,
  updated_at: null,
};

class SettingsState {
  /** The saved settings, replaced whole on every load and never mutated. */
  current = $state.raw(INITIAL_SETTINGS);

  // Appearance is intentionally local-only.
  show_background_image = $state(loadAppearancePreferences().showBackgroundImage);

  constructor() {
    followQuery<AppSettingsRead>(getSettingsOptions().queryKey, (data) => this.load(data));
  }

  get initial_tab(): "art" | "themes" {
    return this.current.workflow === "themes" ? "themes" : "art";
  }

  /** The configured media server as users know it, such as "Plex". */
  get media_server_name() {
    const server = this.current.media_server;
    return server ? SERVER_DISPLAY_NAMES[server] : "media server";
  }

  /** Settings left out of *data* take their defaults. */
  load(data: Partial<AppSettingsRead>) {
    this.current = { ...INITIAL_SETTINGS, ...data };
  }

  /** Every editable setting, without the read-only extras. */
  toUpdatePayload() {
    const {
      media_server: _server,
      tmdb_configured: _tmdb,
      updated_at: _updated,
      ...editable
    } = this.current;
    return editable;
  }
}

export const settingsState = new SettingsState();
