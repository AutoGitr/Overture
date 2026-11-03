import { describe, expect, it } from "vitest";
import type { SelectableServerAuditResult } from "../../../lib/stores/serverAuditState.svelte";
import {
  auditRowKey,
  selectedArtAuditResults,
  selectedThemeAuditResults,
} from "../../../lib/utils/serverAuditPopup";

function artResult(
  overrides: Partial<SelectableServerAuditResult> = {},
): SelectableServerAuditResult {
  return {
    kind: "art",
    item_id: 1,
    season_id: null,
    art_type: "poster",
    title: "Movie",
    status: "phash_mismatch",
    selected: true,
    refreshed: false,
    ...overrides,
  };
}

function themeResult(
  overrides: Partial<SelectableServerAuditResult> = {},
): SelectableServerAuditResult {
  return {
    kind: "theme",
    item_id: 1,
    art_type: "theme",
    server_item_id: "server-1",
    theme_id: "theme-1",
    title: "Movie",
    status: "theme_mismatch",
    selected: true,
    refreshed: false,
    ...overrides,
  };
}

describe("selectedArtAuditResults", () => {
  it("keeps only selected, not-yet-refreshed art results", () => {
    const results = [
      artResult(),
      artResult({ selected: false }),
      artResult({ refreshed: true }),
      themeResult(),
    ];
    expect(selectedArtAuditResults(results)).toEqual([results[0]]);
  });
});

describe("selectedThemeAuditResults", () => {
  it("keeps only selected, not-yet-refreshed theme results with a known server item", () => {
    const results = [
      themeResult(),
      themeResult({ selected: false }),
      themeResult({ refreshed: true }),
      themeResult({ server_item_id: "" }),
      themeResult({ status: "theme_unknown" }),
      artResult(),
    ];
    expect(selectedThemeAuditResults(results)).toEqual([results[0]]);
  });
});

describe("auditRowKey", () => {
  it("keys art rows by item, season and art type", () => {
    expect(auditRowKey(artResult({ season_id: 2 }))).toBe("art:1:2:poster");
    expect(auditRowKey(artResult())).toBe("art:1::poster");
  });

  it("keys theme rows by item, server item and server theme", () => {
    expect(auditRowKey(themeResult())).toBe("theme:1:server-1:theme-1");
    expect(auditRowKey(themeResult({ server_item_id: null, theme_id: null }))).toBe("theme:1::");
  });
});
