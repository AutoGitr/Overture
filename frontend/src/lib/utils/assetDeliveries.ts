import type { AssetRead } from "../../generated/rest/types.gen";

/**
 * Says which of an asset's required places do not yet hold Overture's chosen
 * content, naming each server copy by *serverTitle*; null when nothing is
 * chosen, the asset is not needed, or every required place holds it.
 */
export function deliveryNote(
  asset: AssetRead,
  serverTitle: (serverId: number) => string,
): string | null {
  const selected = !!(asset.url || asset.upload_hash || asset.youtube_id);
  if (!asset.needed || !selected) return null;
  const missing = asset.deliveries.filter((delivery) => delivery.required && !delivery.delivered);
  if (!missing.length) return null;
  const places = missing.map((delivery) =>
    delivery.server_id === null ? "in the folder" : `on ${serverTitle(delivery.server_id)}`,
  );
  return `Not yet ${[...new Set(places)].join(", ")}`;
}
