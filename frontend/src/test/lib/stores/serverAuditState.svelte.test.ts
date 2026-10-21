import { beforeEach, describe, expect, it } from "vitest";
import type { ServerAuditResult } from "../../../generated/ws";
import { serverAuditState } from "../../../lib/stores/serverAuditState.svelte";

function auditResult(overrides: Partial<ServerAuditResult> = {}): ServerAuditResult {
  return {
    kind: "art",
    item_id: 1,
    art_type: "poster",
    status: "phash_mismatch",
    title: "Alien",
    ...overrides,
  };
}

describe("serverAuditState", () => {
  beforeEach(() => serverAuditState.reset());

  it("streams every finding the server reports while the audit runs, selected", () => {
    serverAuditState.handleStarted({ total: 3 });
    serverAuditState.handleProgress({
      done: 1,
      results: [
        auditResult({ item_id: 1, status: "server_missing" }),
        auditResult({ item_id: 2, art_type: "background", hamming: 7 }),
      ],
      results_found: 2,
    });

    expect(serverAuditState.items).toEqual([
      expect.objectContaining({ item_id: 1, selected: true }),
      expect.objectContaining({ item_id: 2, selected: true }),
    ]);
    expect(serverAuditState.found).toBe(2);
  });

  it("stops counting results as selected once fixed", () => {
    serverAuditState.handleCompleted({
      results: [
        auditResult({ item_id: 1, hamming: 7 }),
        auditResult({ item_id: 2, hamming: 7, refreshed: true }),
      ],
    });

    expect(serverAuditState.items.map((result) => result.selected)).toEqual([true, false]);
    expect(serverAuditState.selectedItems.map((result) => result.item_id)).toEqual([1]);
  });

  it("applies same-length terminal snapshot patches", () => {
    serverAuditState.handleCompleted({ results: [auditResult({ hamming: 5 })] });
    serverAuditState.handleCompleted({ results: [auditResult({ hamming: 5, refreshed: true })] });

    expect(serverAuditState.items[0]?.refreshed).toBe(true);
  });

  it("tracks whether the audit has run in this session", () => {
    expect(serverAuditState.hasRun).toBe(false);

    serverAuditState.handleStarted({ total: 1 });
    expect(serverAuditState.hasRun).toBe(true);

    serverAuditState.reset();
    expect(serverAuditState.hasRun).toBe(false);
  });
});
