import { afterEach, describe, expect, it } from "vitest";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { librariesByServer, librarySummary } from "../../../lib/utils/libraries.svelte";
import { appSettings, mediaServers } from "../../helpers/fixtures";

const libraries = [
  { id: "2:films", title: "Films", server_id: 2 },
  { id: "1:movies", title: "Movies", server_id: 1 },
  { id: "1:shows", title: "Shows", server_id: 1 },
];

afterEach(() => settingsState.reset());

describe("librariesByServer", () => {
  it("groups libraries under their server in the order MEDIA_SERVERS lists them", () => {
    settingsState.load(appSettings({ media_servers: mediaServers("plex", "jellyfin") }));

    expect(
      librariesByServer(libraries).map((group) => [
        group.label,
        group.libraries.map((library) => library.title),
      ]),
    ).toEqual([
      ["Plex", ["Movies", "Shows"]],
      ["Jellyfin", ["Films"]],
    ]);
  });

  it("leaves the group unnamed when one server is configured", () => {
    settingsState.load(appSettings({ media_servers: mediaServers("plex") }));

    expect(librariesByServer(libraries)).toEqual([
      expect.objectContaining({ label: "", libraries: libraries.slice(1) }),
    ]);
  });
});

describe("librarySummary", () => {
  it("names each library after its server when several are configured, unknown ones by ID", () => {
    settingsState.load(appSettings({ media_servers: mediaServers("plex", "jellyfin") }));

    expect(librarySummary(["2:films", "gone"], libraries)).toBe("Jellyfin · Films, gone");
  });
});
