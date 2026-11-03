import { describe, expect, it } from "vitest";
import {
  extractYouTubeId,
  formatThemeDuration,
  isYouTubeUrl,
  mergeThemeResults,
  youtubeEmbedUrl,
  youtubeShortUrl,
} from "../../../lib/utils/themeSearch";
import { mediaItem, themeSearchResult } from "../../helpers/fixtures";

describe("themeSearch helpers", () => {
  it("formats durations consistently for theme result cards", () => {
    expect(formatThemeDuration(undefined)).toBe("");
    expect(formatThemeDuration(0)).toBe("");
    expect(formatThemeDuration(65)).toBe("1:05");
    expect(formatThemeDuration(3661.8)).toBe("61:01");
  });

  it("recognizes supported YouTube URL shapes and extracts video ids", () => {
    expect(isYouTubeUrl("https://www.youtube.com/watch?v=abc123_DEF0")).toBe(true);
    expect(isYouTubeUrl("https://youtu.be/abc123_DEF0")).toBe(true);
    expect(isYouTubeUrl("https://www.youtube.com/shorts/abc123_DEF0")).toBe(true);
    expect(isYouTubeUrl("https://example.com/watch?v=abc123_DEF0")).toBe(false);

    expect(extractYouTubeId("https://www.youtube.com/watch?v=abc123_DEF0")).toBe("abc123_DEF0");
    expect(extractYouTubeId("https://youtu.be/abc123_DEF0")).toBe("abc123_DEF0");
    expect(extractYouTubeId("not a youtube url")).toBeNull();
  });

  it("builds consistent display and embed urls", () => {
    expect(youtubeShortUrl("abc123_DEF0")).toBe("https://youtu.be/abc123_DEF0");
    expect(youtubeEmbedUrl("abc123_DEF0")).toBe(
      "https://www.youtube-nocookie.com/embed/abc123_DEF0",
    );
  });

  describe("mergeThemeResults", () => {
    it("orders currently selected first, then OvertureDB, then ThemerrDB, then search results", () => {
      const item = mediaItem({
        title: "Alien",
        youtube_id: "selected_yt",
        youtube_title: "Alien Main Title",
        youtube_duration: 120,
      });
      const searchResults = [
        themeSearchResult({ id: "search_1", title: "Alien Ost 1" }),
        themeSearchResult({ id: "search_2", title: "Alien Ost 2" }),
      ];

      const merged = mergeThemeResults({
        item,
        overtureDbId: "overture_yt",
        themerrDbId: "themerr_yt",
        searchResults,
      });

      expect(merged).toHaveLength(5);
      expect(merged[0]?.id).toBe("selected_yt");
      expect(merged[0]?.badges).toEqual([{ label: "Currently Selected", variant: "success" }]);
      expect(merged[0]?.title).toBe("Alien Main Title");

      expect(merged[1]?.id).toBe("overture_yt");
      expect(merged[1]?.badges).toEqual([{ label: "OvertureDB", variant: "accent" }]);

      expect(merged[2]?.id).toBe("themerr_yt");
      expect(merged[2]?.badges).toEqual([{ label: "ThemerrDB", variant: "warning" }]);

      expect(merged[3]?.id).toBe("search_1");
      expect(merged[3]?.badges).toEqual([]);

      expect(merged[4]?.id).toBe("search_2");
      expect(merged[4]?.badges).toEqual([]);
    });

    it("deduplicates when OvertureDB matches currently selected video and combines badges", () => {
      const item = mediaItem({
        title: "Alien",
        youtube_id: "shared_yt",
        youtube_title: "Alien Theme",
      });

      const merged = mergeThemeResults({
        item,
        overtureDbId: "shared_yt",
        themerrDbId: "themerr_yt",
      });

      expect(merged).toHaveLength(2);
      expect(merged[0]?.id).toBe("shared_yt");
      expect(merged[0]?.badges).toEqual([
        { label: "Currently Selected", variant: "success" },
        { label: "OvertureDB", variant: "accent" },
      ]);
      expect(merged[1]?.id).toBe("themerr_yt");
      expect(merged[1]?.badges).toEqual([{ label: "ThemerrDB", variant: "warning" }]);
    });

    it("deduplicates search results that match existing selected or dataset themes and enriches metadata", () => {
      const item = mediaItem({
        title: "Alien",
        youtube_id: "selected_yt",
      });
      const searchResults = [
        themeSearchResult({
          id: "overture_yt",
          title: "Alien (1979) Suite - High Quality",
          channel: "Soundtrack Masters",
          duration: 310,
        }),
        themeSearchResult({
          id: "selected_yt",
          title: "Alien Opening Credits",
          channel: "Fox Music",
          duration: 155,
        }),
        themeSearchResult({
          id: "search_unique",
          title: "Unique Result",
        }),
      ];

      const merged = mergeThemeResults({
        item,
        overtureDbId: "overture_yt",
        searchResults,
      });

      expect(merged).toHaveLength(3);
      // Selected first
      expect(merged[0]?.id).toBe("selected_yt");
      expect(merged[0]?.title).toBe("Alien Opening Credits");
      expect(merged[0]?.channel).toBe("Fox Music");
      expect(merged[0]?.duration).toBe(155);
      expect(merged[0]?.badges).toEqual([{ label: "Currently Selected", variant: "success" }]);

      // OvertureDB second
      expect(merged[1]?.id).toBe("overture_yt");
      expect(merged[1]?.title).toBe("Alien (1979) Suite - High Quality");
      expect(merged[1]?.channel).toBe("Soundtrack Masters");
      expect(merged[1]?.duration).toBe(310);
      expect(merged[1]?.badges).toEqual([{ label: "OvertureDB", variant: "accent" }]);

      // Unique search result third
      expect(merged[2]?.id).toBe("search_unique");
      expect(merged[2]?.badges).toEqual([]);
    });

    it("handles null or missing item and empty inputs gracefully", () => {
      const merged = mergeThemeResults({
        item: null,
        overtureDbId: null,
        themerrDbId: null,
        searchResults: [],
      });
      expect(merged).toEqual([]);
    });
  });
});
