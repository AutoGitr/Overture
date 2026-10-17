import { describe, expect, it } from "vitest";
import {
  DEFAULT_ACCENT,
  DEFAULT_DARK_BG,
  DEFAULT_LIGHT_ACCENT,
  DEFAULT_LIGHT_BG,
  applyAppearancePreferences,
  loadAppearancePreferences,
  normalizeHexColor,
  saveAppearancePreferences,
} from "../../../lib/utils/appearance";

describe("appearance preferences", () => {
  it("uses the light palette when light mode has no saved colors", () => {
    localStorage.setItem("theme", JSON.stringify("light"));
    const prefs = loadAppearancePreferences();
    expect(prefs.accentColor).toBe(DEFAULT_LIGHT_ACCENT);
    expect(prefs.bgColor).toBe(DEFAULT_LIGHT_BG);
    applyAppearancePreferences(prefs);
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("");
  });

  it("falls back to dark defaults when stored values are absent", () => {
    expect(loadAppearancePreferences()).toEqual({
      theme: "dark",
      accentColor: DEFAULT_ACCENT,
      bgColor: DEFAULT_DARK_BG,
      showBackgroundImage: true,
    });
  });

  it("round-trips saved preferences and applies document attributes", () => {
    const themeColor = document.createElement("meta");
    themeColor.name = "theme-color";
    document.head.append(themeColor);

    saveAppearancePreferences({
      theme: "light",
      accentColor: "#ff0055",
      bgColor: "#ffffff",
      showBackgroundImage: false,
    });

    expect(loadAppearancePreferences()).toEqual({
      theme: "light",
      accentColor: "#ff0055",
      bgColor: "#ffffff",
      showBackgroundImage: false,
    });

    applyAppearancePreferences(loadAppearancePreferences());

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("#ff0055");
    expect(document.documentElement.style.getPropertyValue("--bg-root")).toBe("#ffffff");
    expect(themeColor).toHaveAttribute("content", "#ffffff");
  });

  it("removes custom styles when defaults are restored", () => {
    applyAppearancePreferences({
      theme: "dark",
      accentColor: "#ff0055",
      bgColor: "#123456",
      showBackgroundImage: true,
    });
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("#ff0055");
    expect(document.documentElement.style.getPropertyValue("--bg-root")).toBe("#123456");

    applyAppearancePreferences({
      theme: "dark",
      accentColor: DEFAULT_ACCENT,
      bgColor: DEFAULT_DARK_BG,
      showBackgroundImage: true,
    });

    expect(document.documentElement).not.toHaveAttribute("data-theme");
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("");
    expect(document.documentElement.style.getPropertyValue("--bg-root")).toBe("");
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
