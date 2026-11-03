import { beforeEach, describe, expect, it } from "vitest";
import { persistedState } from "../../../lib/utils/persistedState.svelte";

describe("persistedState", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("starts from the declared defaults when nothing is stored", () => {
    const config = persistedState("demo", {
      enabled: true,
      count: 3,
      label: "hours",
      items: ["a"],
    });

    expect(config.enabled).toBe(true);
    expect(config.count).toBe(3);
    expect(config.label).toBe("hours");
    expect(config.items).toEqual(["a"]);
  });

  it("writes nothing until save is called", () => {
    const config = persistedState("demo", { enabled: true });

    config.enabled = false;
    expect(localStorage.getItem("demo_enabled")).toBeNull();

    config.save();
    expect(localStorage.getItem("demo_enabled")).toBe("false");
  });

  it("round-trips every value type through storage", () => {
    const first = persistedState("demo", {
      enabled: true,
      count: 0,
      label: "hours",
      items: [] as string[],
    });
    first.enabled = false;
    first.count = 7;
    first.label = "days";
    first.items = ["poster", "background"];
    first.save();

    const second = persistedState("demo", {
      enabled: true,
      count: 0,
      label: "hours",
      items: [] as string[],
    });

    expect(second.enabled).toBe(false);
    expect(second.count).toBe(7);
    expect(second.label).toBe("days");
    expect(second.items).toEqual(["poster", "background"]);
  });

  it("falls back to the default when a stored value is unreadable", () => {
    localStorage.setItem("demo_items", "not json");
    localStorage.setItem("demo_count", "abc");

    const config = persistedState("demo", { items: ["a"], count: 5 });

    expect(config.items).toEqual(["a"]);
    expect(config.count).toBe(5);
  });

  it("passes a stored value through revive before it becomes state", () => {
    localStorage.setItem("demo_threshold", "99");

    const config = persistedState("demo", {
      threshold: {
        default: 0,
        revive: (value: number) => Math.max(-1, Math.min(10, value)),
      },
    });

    expect(config.threshold).toBe(10);
  });

  it("revives the default too, so a fresh install is normalised as well", () => {
    const config = persistedState("demo", {
      sources: {
        default: ["b", "a", "b"],
        revive: (value: string[]) => [...new Set(value)].sort(),
      },
    });

    expect(config.sources).toEqual(["a", "b"]);
  });

  it("keeps separate prefixes from colliding", () => {
    const art = persistedState("art", { enabled: true });
    const themes = persistedState("themes", { enabled: true });

    art.enabled = false;
    art.save();
    themes.save();

    expect(localStorage.getItem("art_enabled")).toBe("false");
    expect(localStorage.getItem("themes_enabled")).toBe("true");
  });

  it("survives storage that throws on read and write", () => {
    const original = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new Error("storage blocked");
      },
    });

    try {
      const config = persistedState("demo", { enabled: true });
      expect(config.enabled).toBe(true);
      expect(() => config.save()).not.toThrow();
    } finally {
      if (original) Object.defineProperty(window, "localStorage", original);
    }
  });
});
