import { describe, expect, it } from "vitest";
import {
  DEFAULT_ACCENT,
  DEFAULT_APPEARANCE,
  applyAppearancePreferences,
  loadAppearancePreferences,
  normalizeHexColor,
  resolvedTheme,
  saveAppearancePreferences,
} from "../../../lib/utils/appearance";

describe("appearance preferences", () => {
  it("follows the device and keeps the one default accent when nothing is saved", () => {
    expect(loadAppearancePreferences()).toEqual(DEFAULT_APPEARANCE);
    expect(DEFAULT_APPEARANCE).toMatchObject({ theme: "system", accentColor: DEFAULT_ACCENT });
    // The test device prefers dark mode.
    expect(resolvedTheme("system")).toBe("dark");
    applyAppearancePreferences(loadAppearancePreferences());
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(document.documentElement.style.getPropertyValue("--accent-color")).toBe("");
  });

  it("round-trips saved preferences and applies document attributes", () => {
    const themeColor = document.createElement("meta");
    themeColor.name = "theme-color";
    document.head.append(themeColor);
    document.body.style.backgroundColor = "rgb(250, 248, 245)";

    saveAppearancePreferences({
      theme: "light",
      contrast: "more",
      accentColor: "#ff0055",
      showBackgroundImage: false,
    });

    expect(loadAppearancePreferences()).toEqual({
      theme: "light",
      contrast: "more",
      accentColor: "#ff0055",
      showBackgroundImage: false,
    });

    applyAppearancePreferences(loadAppearancePreferences());

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(document.documentElement).toHaveAttribute("data-contrast", "more");
    expect(document.documentElement.style.getPropertyValue("--accent-color")).toBe("#ff0055");
    // The browser's address bar takes the page's own background.
    expect(themeColor).toHaveAttribute("content", "rgb(250, 248, 245)");
  });

  it("removes custom styles when defaults are restored", () => {
    applyAppearancePreferences({
      ...DEFAULT_APPEARANCE,
      contrast: "more",
      accentColor: "#ff0055",
    });
    expect(document.documentElement.style.getPropertyValue("--accent-color")).toBe("#ff0055");

    applyAppearancePreferences(DEFAULT_APPEARANCE);

    expect(document.documentElement).not.toHaveAttribute("data-contrast");
    expect(document.documentElement.style.getPropertyValue("--accent-color")).toBe("");
  });

  it("replaces unknown stored values with the defaults", () => {
    localStorage.setItem("theme", JSON.stringify("sepia"));
    localStorage.setItem("contrast", JSON.stringify("max"));
    localStorage.setItem("accentColor", JSON.stringify("nope"));

    expect(loadAppearancePreferences()).toEqual(DEFAULT_APPEARANCE);
  });

  describe("normalizeHexColor", () => {
    it("accepts valid 6-digit hex colors with or without hash", () => {
      expect(normalizeHexColor("#6366f1")).toBe("#6366f1");
      expect(normalizeHexColor("6366f1")).toBe("#6366f1");
      expect(normalizeHexColor("#FFFFFF")).toBe("#ffffff");
      expect(normalizeHexColor("AbCdEf")).toBe("#abcdef");
    });

    it("accepts valid 3-digit hex shorthand and expands to 6 digits", () => {
      expect(normalizeHexColor("#fff")).toBe("#ffffff");
      expect(normalizeHexColor("fff")).toBe("#ffffff");
      expect(normalizeHexColor("#f05")).toBe("#ff0055");
      expect(normalizeHexColor("A1B")).toBe("#aa11bb");
    });

    it("trims surrounding whitespace", () => {
      expect(normalizeHexColor("   #6366f1   ")).toBe("#6366f1");
      expect(normalizeHexColor("  fff  ")).toBe("#ffffff");
    });

    it("rejects invalid hex formats and color names", () => {
      expect(normalizeHexColor("")).toBeNull();
      expect(normalizeHexColor("   ")).toBeNull();
      expect(normalizeHexColor("blue")).toBeNull();
      expect(normalizeHexColor("#12")).toBeNull();
      expect(normalizeHexColor("#1234")).toBeNull();
      expect(normalizeHexColor("#12345")).toBeNull();
      expect(normalizeHexColor("#1234567")).toBeNull();
      expect(normalizeHexColor("#12345678")).toBeNull();
      expect(normalizeHexColor("zzz")).toBeNull();
      expect(normalizeHexColor("#gg0000")).toBeNull();
    });
  });
});
