import type { AssetRead } from "../../generated/rest/types.gen";

/** The places the asset has to be that do not hold its content. */
function undelivered(asset: AssetRead): AssetRead["deliveries"] {
  return asset.deliveries.filter((delivery) => delivery.required && !delivery.delivered);
}

/**
 * Says which of an asset's required places do not yet hold Overture's chosen
 * content, naming each server copy by *serverTitle*; null when nothing is
 * chosen, the asset is not needed, or every required place holds it.
 */
export function deliveryNote(
  asset: AssetRead,
  serverTitle: (serverId: number) => string,
): string | null {
  if (!asset.needed || !asset.selected) return null;
  const missing = undelivered(asset);
  if (!missing.length) return null;
  const places = missing.map((delivery) =>
    delivery.server_id === null ? "in the folder" : `on ${serverTitle(delivery.server_id)}`,
  );
  return `Not yet ${[...new Set(places)].join(", ")}`;
}

/** Whether the asset's selection is in every place it has to be. */
export function isDelivered(asset: AssetRead): boolean {
  return asset.selected && !undelivered(asset).length;
}

/** Whether an asset has a selection, or anything in place, to clear. */
export function holdsSomething(asset: AssetRead): boolean {
  return asset.selected || asset.deliveries.some((delivery) => delivery.present);
}
