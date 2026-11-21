import type { AssetRead } from "../../generated/rest/types.gen";

/**
 * Says which of an asset's required places do not hold Overture's content,
 * naming each server copy by *serverTitle*; null when every place does.
 */
export function deliveryNote(
  asset: AssetRead,
  serverTitle: (serverId: number) => string,
): string | null {
  const missing = asset.deliveries.filter((delivery) => delivery.required && !delivery.delivered);
  if (!missing.length) return null;
  const places = missing.map((delivery) =>
    delivery.server_id === null ? "in the folder" : `on ${serverTitle(delivery.server_id)}`,
  );
  return `Not yet ${[...new Set(places)].join(", ")}`;
}
