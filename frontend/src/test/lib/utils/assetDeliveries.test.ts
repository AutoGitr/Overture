import { describe, expect, it } from "vitest";
import type { AssetDeliveryRead } from "../../../generated/rest/types.gen";
import { deliveryNote, holdsSomething, isDelivered } from "../../../lib/utils/assetDeliveries";
import { asset } from "../../helpers/fixtures";

function delivery(overrides: Partial<AssetDeliveryRead>): AssetDeliveryRead {
  return {
    server_id: 1,
    channel: "upload",
    required: true,
    delivered: true,
    present: true,
    checked_at: null,
    ...overrides,
  };
}

const titles: Record<number, string> = { 1: "Plex", 2: "Jellyfin" };
const serverTitle = (id: number) => titles[id] ?? `Server ${id}`;

describe("delivery notes", () => {
  it("names each required place that lacks Overture's content", () => {
    const poster = asset("poster", {
      url: "https://image.tmdb.org/t/p/original/a.jpg",
      deliveries: [
        delivery({ server_id: 1 }),
        delivery({ server_id: 2, delivered: false }),
        delivery({ server_id: 3, delivered: false, required: false }),
      ],
    });
    expect(deliveryNote(poster, serverTitle)).toBe("Not yet on Jellyfin");
  });

  it("names a title's folder for its local file", () => {
    const theme = asset("theme", {
      youtube_id: "yt1",
      deliveries: [delivery({ server_id: null, channel: "file", delivered: false })],
    });
    expect(deliveryNote(theme, serverTitle)).toBe("Not yet in the folder");
  });

  it("says nothing when unneeded, unselected, or every required place holds it", () => {
    expect(
      deliveryNote(
        asset("poster", {
          url: "https://image.tmdb.org/t/p/original/a.jpg",
          deliveries: [delivery({})],
        }),
        serverTitle,
      ),
    ).toBeNull();
    expect(
      deliveryNote(
        asset("background", {
          needed: false,
          deliveries: [delivery({ server_id: 1, delivered: false })],
        }),
        serverTitle,
      ),
    ).toBeNull();
    expect(
      deliveryNote(
        asset("poster", {
          status: "missing",
          deliveries: [delivery({ server_id: null, channel: "file", delivered: false })],
        }),
        serverTitle,
      ),
    ).toBeNull();
    expect(deliveryNote(asset("poster"), serverTitle)).toBeNull();
  });
});

describe("what an asset holds", () => {
  it("has something to clear once it selects something or anything is in place", () => {
    expect(holdsSomething(asset("theme"))).toBe(false);
    expect(holdsSomething(asset("theme", { youtube_id: "abcDEF123_4" }))).toBe(true);
    expect(holdsSomething(asset("poster", { upload_hash: "a".repeat(64) }))).toBe(true);
    const shown = asset("theme", { deliveries: [delivery({ delivered: false })] });
    expect(holdsSomething(shown)).toBe(true);
    const empty = asset("theme", { deliveries: [delivery({ delivered: false, present: false })] });
    expect(holdsSomething(empty)).toBe(false);
  });

  it("is delivered once its selection is in every required place", () => {
    expect(isDelivered(asset("theme", { youtube_id: "yt1" }))).toBe(true);
    const lacking = asset("theme", {
      youtube_id: "yt1",
      deliveries: [delivery({}), delivery({ server_id: 2, delivered: false })],
    });
    expect(isDelivered(lacking)).toBe(false);
    // Complete because nothing is wanted, yet nothing is chosen or delivered.
    expect(isDelivered(asset("theme", { status: "complete", needed: false }))).toBe(false);
  });
});
