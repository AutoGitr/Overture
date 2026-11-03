import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isImageLoaded, markImageLoaded, preloadImages } from "../../../lib/utils/imagePreload";

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

describe("image preloading", () => {
  beforeEach(() => {
    FakeImage.started = [];
    vi.stubGlobal("Image", FakeImage);
  });

  // The queues are module state: drain them so the next test starts idle.
  afterEach(() => {
    vi.unstubAllGlobals();
    preloadImages([], "next");
    preloadImages([], "sidebar");
    for (const image of FakeImage.started) image.onerror?.();
  });

  it("fetches a few at a time, at low priority, without a referrer", () => {
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

  it("puts the next item first and fetches only the latest sources of each purpose", () => {
    preloadImages(["/busy-1", "/busy-2", "/busy-3"], "sidebar");
    preloadImages(["/old-window"], "sidebar");
    preloadImages(["/old-next"], "next");
    preloadImages(["/next"], "next");
    // The window moved: the old one is no longer wanted.
    preloadImages(["/new-window"], "sidebar");
    for (const image of [...FakeImage.started]) image.onerror?.();

    expect(startedSources()).toEqual(["/busy-1", "/busy-2", "/busy-3", "/next", "/new-window"]);
  });

  it("fetches a source both purposes want once", () => {
    preloadImages(["/busy-1", "/busy-2", "/busy-3"], "sidebar");
    preloadImages(["/shared"], "sidebar");
    preloadImages(["/shared"], "next");
    FakeImage.started[0]?.onerror?.();
    FakeImage.started[1]?.onerror?.();

    expect(startedSources()).toEqual(["/busy-1", "/busy-2", "/busy-3", "/shared"]);
  });

  it("never fetches an image again once loaded", () => {
    markImageLoaded("/shown");

    preloadImages(["/shown"], "next");

    expect(FakeImage.started).toEqual([]);
  });

  it("fetches nothing ahead when the browser asks to save data", () => {
    vi.stubGlobal("navigator", { connection: { saveData: true } });

    preloadImages(["/saved"], "next");

    expect(FakeImage.started).toEqual([]);
  });
});
