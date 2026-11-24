import { getSettingsOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
import type { AppSettingsRead, MediaServerRead, ServerType } from "../../generated/rest/types.gen";
import { followQuery } from "../rest/queryClient";
import { DEFAULT_APP_SETTINGS } from "../../generated/settings";
import { loadAppearancePreferences } from "../utils/appearance";

/** What the dashboard assumes until the saved settings arrive. */
const INITIAL_SETTINGS: AppSettingsRead = {
  ...DEFAULT_APP_SETTINGS,
  media_servers: [],
  tmdb_configured: false,
  mdblist_configured: false,
  radarr_configured: false,
  sonarr_configured: false,
  collections_supported: false,
  collection_themes_unavailable: null,
  art_download_workers: 1,
  theme_download_workers: 1,
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

  /** The configured media servers, the lead first. */
  get servers(): MediaServerRead[] {
    return this.current.media_servers;
  }

  /** The configured server the database numbers *id*, if it is configured. */
  server(id: number): MediaServerRead | undefined {
    return this.servers.find((server) => server.id === id);
  }

  /**
   * How the server the database numbers *id* is named: as configured now, else
   * by the *name* it had when something recorded it, else by its number.
   */
  serverTitle(id: number, name?: string | null): string {
    return this.server(id)?.title ?? name ?? `Server ${id}`;
  }

  /**
   * How a library is named to users: after its server too when more than one
   * is configured, as libraries of several servers can share a title.
   */
  libraryLabel(library: { title: string; server_id: number }): string {
    const server = this.multipleServers ? this.server(library.server_id) : undefined;
    return server ? `${server.title} · ${library.title}` : library.title;
  }

  /** Whether more than one media server is configured, so names tell them apart. */
  get multipleServers() {
    return this.servers.length > 1;
  }

  /** Whether a configured server is of *type*. */
  hasServerType(type: ServerType) {
    return this.servers.some((server) => server.type === type);
  }

  /** The configured media servers as users know them, such as "Plex and Jellyfin". */
  get media_server_name() {
    return this.serverNames(this.servers.map((server) => server.id));
  }

  /** The servers *ids* number, as users know them, in MEDIA_SERVERS order. */
  serverNames(ids: readonly number[]): string {
    const titles = this.servers
      .filter((server) => ids.includes(server.id))
      .map((server) => server.title);
    if (titles.length === 0) return "media server";
    if (titles.length === 1) return titles[0]!;
    return `${titles.slice(0, -1).join(", ")} and ${titles[titles.length - 1]}`;
  }

  /** Loaded settings say MEDIA_SERVERS=none: no server to sync, audit or manage. */
  get standalone() {
    return this.current !== INITIAL_SETTINGS && this.servers.length === 0;
  }

  /** Replace the complete response; form drafts never enter this adapter. */
  load(data: AppSettingsRead) {
    this.current = data;
  }

  reset() {
    this.current = INITIAL_SETTINGS;
  }

  /** Every editable setting, without the read-only extras. */
  toUpdatePayload() {
    const {
      media_servers: _servers,
      tmdb_configured: _tmdb,
      mdblist_configured: _mdblist,
      radarr_configured: _radarr,
      sonarr_configured: _sonarr,
      collections_supported: _collections,
      collection_themes_unavailable: _collectionThemes,
      art_download_workers: _artWorkers,
      theme_download_workers: _themeWorkers,
      updated_at: _updated,
      ...editable
    } = this.current;
    return editable;
  }
}

export const settingsState = new SettingsState();

/** Every editable setting, as the settings popup edits them. */
export type SettingsDraft = ReturnType<SettingsState["toUpdatePayload"]>;
