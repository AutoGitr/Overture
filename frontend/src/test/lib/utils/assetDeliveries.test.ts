import { describe, expect, it } from "vitest";
import type { AssetDeliveryRead } from "../../../generated/rest/types.gen";
import { deliveryNote } from "../../../lib/utils/assetDeliveries";
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
      deliveries: [delivery({ server_id: null, channel: "file", delivered: false })],
    });
    expect(deliveryNote(theme, serverTitle)).toBe("Not yet in the folder");
  });

  it("says nothing once every required place holds it", () => {
    expect(deliveryNote(asset("poster", { deliveries: [delivery({})] }), serverTitle)).toBeNull();
    expect(deliveryNote(asset("poster"), serverTitle)).toBeNull();
  });
});
