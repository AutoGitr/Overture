import { screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import DetailPanel from "../../../lib/components/DetailPanel.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { navigate } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { appSettings, mediaItem, season } from "../../helpers/fixtures";
import { mockFetchRoutes } from "../../helpers/fetch";
import { renderWithQueryClient } from "../../helpers/render";

/**
 * The detail view as it is composed: the header's paste and upload buttons
 * come before the art panel, so they update first when the view changes.
 */
describe("DetailPanel seasons", () => {
  const show = mediaItem({ id: 7, media_type: "show", title: "Firefly" });

  beforeEach(async () => {
    queryClient.clear();
    settingsState.load(appSettings({ auto_match_art: false }));
    mockFetchRoutes({
      "/api/library/items/7/seasons": [1, 2].map((num) =>
        season({ id: num, media_item_id: 7, season_num: num, title: `Season ${num}` }),
      ),
      "/api/library/items/7/art/season_poster/sources": { current_url: null, sources: {} },
    });
    await navigate("/shows", { replace: true });
  });

  it("offers the header's buttons for the season shown, and none once it is left", async () => {
    const { rerender } = renderWithQueryClient(DetailPanel, {
      item: show,
      view: { mode: "art", artSubTab: "seasons", drillSeasonNum: 1 },
    });
    expect(
      await screen.findByRole("button", { name: "Paste URL & save as season poster" }),
    ).toBeInTheDocument();

    await rerender({
      item: show,
      view: { mode: "art", artSubTab: "seasons", drillSeasonNum: null },
    });

    await waitFor(() => expect(screen.queryByRole("button", { name: /Paste URL/ })).toBeNull());
    expect(screen.queryByRole("button", { name: /Upload image/ })).toBeNull();
  });
});
