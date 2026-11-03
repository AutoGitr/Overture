import { describe, expect, it, vi } from "vitest";
import { readJson, writeJson } from "../../../lib/utils/storage";

describe("JSON storage", () => {
  it("isolates local and session preferences", () => {
    writeJson("key", "local");
    writeJson("key", "session", "session");
    expect(readJson("key", "")).toBe("local");
    expect(readJson("key", "", "session")).toBe("session");
  });

  it.each([false, 42, "days", ["poster"], { libraryIds: ["1"] }])(
    "round-trips %j as JSON",
    (value) => {
      writeJson("value", value);
      expect(JSON.parse(localStorage.getItem("value")!)).toEqual(value);
      expect(readJson("value", value)).toEqual(value);
    },
  );

  it.each([
    ["{", { ok: true }],
    ['"false"', true],
    ["null", []],
    ["{}", []],
    ["[]", {}],
    ["1e999", 12],
    ["false", "dark"],
  ])("falls back for malformed or incorrectly typed values", (raw, fallback) => {
    localStorage.setItem("value", String(raw));
    expect(readJson("value", fallback)).toEqual(fallback);
  });

  it("returns the fallback for missing preferences", () => {
    expect(readJson("missing", 12)).toBe(12);
  });

  it("leaves object validation to its consumer", () => {
    writeJson("value", { libraryIds: ["1"] });
    expect(readJson<unknown>("value", null)).toEqual({ libraryIds: ["1"] });
  });

  it("degrades to fallbacks when storage access throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readJson("key", "fallback")).toBe("fallback");
    expect(() => writeJson("key", "value")).not.toThrow();
  });

  it("tolerates values that cannot be serialized", () => {
    const value: Record<string, unknown> = {};
    value.self = value;
    expect(() => writeJson("circular", value)).not.toThrow();
  });
});
