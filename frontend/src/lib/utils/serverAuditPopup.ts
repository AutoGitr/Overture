import type { AuditStatus, ServerAuditResult } from "../../generated/ws";
import type { SelectableServerAuditResult } from "../stores/serverAuditState.svelte";

export const AUDIT_STATUS_LABELS: Record<AuditStatus, string> = {
  phash_match: "d=0 Match",
  phash_mismatch: "Mismatch",
  local_missing: "Local Missing",
  server_missing: "Server Missing",
  unresolved_server_id: "No Server ID",
  theme_match: "Theme Match",
  theme_mismatch: "Theme Mismatch",
  theme_server_missing: "Theme Missing",
  theme_unknown: "Theme Unknown",
  error: "Error",
};

/** Selectable, not-yet-fixed art results the user has checked. */
export function selectedArtAuditResults(
  results: SelectableServerAuditResult[],
): SelectableServerAuditResult[] {
  return results.filter((result) => result.kind === "art" && result.selected && !result.refreshed);
}

/** Selectable, not-yet-fixed theme results the user has checked. */
export function selectedThemeAuditResults(
  results: SelectableServerAuditResult[],
): SelectableServerAuditResult[] {
  return results.filter(
    (result) =>
      result.kind === "theme" &&
      result.selected &&
      !result.refreshed &&
      result.server_item_id &&
      result.status !== "theme_unknown",
  );
}

/** Stable key identifying one audit row across result pages and fix runs. */
export function auditRowKey(
  result: Pick<
    ServerAuditResult,
    "kind" | "item_id" | "season_id" | "art_type" | "server_item_id" | "theme_id"
  >,
): string {
  return result.kind === "theme"
    ? `theme:${result.item_id}:${result.server_item_id ?? ""}:${result.theme_id ?? ""}`
    : `art:${result.item_id}:${result.season_id ?? ""}:${result.art_type}`;
}
