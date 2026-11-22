import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import LibraryName from "../../../lib/components/LibraryName.svelte";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { appSettings, mediaServers } from "../../helpers/fixtures";

describe("LibraryName", () => {
  it("names a library after its server, in the server's colours, among several", () => {
    settingsState.load(appSettings({ media_servers: mediaServers("plex", "jellyfin") }));
    const jellyfin = settingsState.servers.find((server) => server.type === "jellyfin")!;

    render(LibraryName, { library: { title: "Movies", server_id: jellyfin.id } });

    expect(screen.getByText(jellyfin.title)).toHaveAttribute("data-server", "jellyfin");
    expect(screen.getByText("Movies")).toBeInTheDocument();
  });

  it("names a library alone when one server is configured", () => {
    settingsState.load(appSettings());
    const [plex] = settingsState.servers;

    const { container } = render(LibraryName, {
      library: { title: "Movies", server_id: plex!.id },
    });

    expect(container).toHaveTextContent(/^\s*Movies\s*$/);
  });
});
