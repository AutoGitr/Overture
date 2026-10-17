import { beforeEach, describe, expect, it, vi } from "vitest";

/** Stands in for `Image`: records each fetch and lets the test finish it. */
class FakeImage {
  static started: FakeImage[] = [];
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  fetchPriority = "";
  decoding = "";
  referrerPolicy = "";
  private source = "";

  get src() {
    return this.source;
  }

  set src(value: string) {
    this.source = value;
    FakeImage.started.push(this);
  }
}

const startedSources = () => FakeImage.started.map((image) => image.src);

async function loadModule() {
  // The registry and queues are module state: each test gets them fresh.
  vi.resetModules();
  return import("../../../lib/utils/imagePreload");
}

describe("image preloading", () => {
  beforeEach(() => {
    FakeImage.started = [];
    vi.stubGlobal("Image", FakeImage);
  });

  it("fetches a few at a time, at low priority, without a referrer", async () => {
    const { preloadImages, isImageLoaded } = await loadModule();

    preloadImages(["/a", "/b", "/c", "/d", null], "sidebar");

    expect(startedSources()).toEqual(["/a", "/b", "/c"]);
    expect(FakeImage.started[0]).toMatchObject({
      fetchPriority: "low",
      decoding: "async",
      referrerPolicy: "no-referrer",
    });
    FakeImage.started[0]?.onload?.();
    expect(isImageLoaded("/a")).toBe(true);
    expect(startedSources()).toEqual(["/a", "/b", "/c", "/d"]);
  });

  it("puts the next item first and fetches only the latest sources of each purpose", async () => {
    const { preloadImages } = await loadModule();

    preloadImages(["/busy-1", "/busy-2", "/busy-3"], "sidebar");
    preloadImages(["/old-window"], "sidebar");
    preloadImages(["/old-next"], "next");
    preloadImages(["/next"], "next");
    // The window moved: the old one is no longer wanted.
    preloadImages(["/new-window"], "sidebar");
    for (const image of [...FakeImage.started]) image.onerror?.();

    expect(startedSources()).toEqual(["/busy-1", "/busy-2", "/busy-3", "/next", "/new-window"]);
  });

  it("never fetches an image again once loaded", async () => {
    const { preloadImages, markImageLoaded } = await loadModule();
    markImageLoaded("/shown");

    preloadImages(["/shown"], "next");

    expect(FakeImage.started).toEqual([]);
  });

  it("fetches nothing ahead when the browser asks to save data", async () => {
    vi.stubGlobal("navigator", { connection: { saveData: true } });
    const { preloadImages } = await loadModule();

    preloadImages(["/a"], "next");

    expect(FakeImage.started).toEqual([]);
  });
});
