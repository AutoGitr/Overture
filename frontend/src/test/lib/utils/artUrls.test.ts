import { describe, expect, it } from "vitest";
import { parseArtUrl } from "../../../lib/utils/artUrls";

describe("parseArtUrl", () => {
  it("returns trimmed http(s) links unchanged for the backend to canonicalise", () => {
    expect(parseArtUrl("  https://image.tmdb.org/t/p/w342/art.jpg \n")).toBe(
      "https://image.tmdb.org/t/p/w342/art.jpg",
    );
    expect(parseArtUrl("http://theposterdb.com/poster/207889")).toBe(
      "http://theposterdb.com/poster/207889",
    );
  });

  it("rejects text and non-web schemes", () => {
    expect(parseArtUrl("")).toBeNull();
    expect(parseArtUrl("Alien (1979)")).toBeNull();
    expect(parseArtUrl("javascript:alert(1)")).toBeNull();
    expect(parseArtUrl("file:///etc/passwd")).toBeNull();
  });
});
