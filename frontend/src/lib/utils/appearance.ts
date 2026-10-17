import { readJson, writeJson } from "./storage";

export interface AppearancePreferences {
  theme: "dark" | "light";
  accentColor: string;
  bgColor: string;
  showBackgroundImage: boolean;
}

export const DEFAULT_DARK_BG = "#0a0c10";
export const DEFAULT_LIGHT_BG = "#f3f4f6";
export const DEFAULT_ACCENT = "#d8c7a3";
export const DEFAULT_LIGHT_ACCENT = "#806844";

export function normalizeHexColor(value: string): string | null {
  const trimmed = value.trim();
  const match = /^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.exec(trimmed);
  if (!match || !match[1]) return null;
  const hex = match[1];
  if (hex.length === 3) {
    const c0 = hex[0];
    const c1 = hex[1];
    const c2 = hex[2];
    return `#${c0}${c0}${c1}${c1}${c2}${c2}`.toLowerCase();
  }
  return `#${hex}`.toLowerCase();
}

export function loadAppearancePreferences(): AppearancePreferences {
  const theme = readJson<string>("theme", "dark") === "light" ? "light" : "dark";
  const defaultBg = theme === "dark" ? DEFAULT_DARK_BG : DEFAULT_LIGHT_BG;
  const defaultAccent = theme === "dark" ? DEFAULT_ACCENT : DEFAULT_LIGHT_ACCENT;
  const rawAccent = readJson<string>("accentColor", defaultAccent);
  const rawBg = readJson<string>("bgColor", defaultBg);
  return {
    theme,
    accentColor: normalizeHexColor(rawAccent) ?? defaultAccent,
    bgColor: normalizeHexColor(rawBg) ?? defaultBg,
    showBackgroundImage: readJson("showBackgroundImage", true),
  };
}

export function saveAppearancePreferences(prefs: AppearancePreferences): void {
  writeJson("theme", prefs.theme);
  writeJson(
    "accentColor",
    normalizeHexColor(prefs.accentColor) ??
      (prefs.theme === "light" ? DEFAULT_LIGHT_ACCENT : DEFAULT_ACCENT),
  );
  writeJson("bgColor", normalizeHexColor(prefs.bgColor) ?? DEFAULT_DARK_BG);
  writeJson("showBackgroundImage", prefs.showBackgroundImage);
}

export function applyAppearancePreferences(prefs: AppearancePreferences): void {
  const defaultAccent = prefs.theme === "light" ? DEFAULT_LIGHT_ACCENT : DEFAULT_ACCENT;
  const accentColor = normalizeHexColor(prefs.accentColor) ?? defaultAccent;
  const defaultBg = prefs.theme === "light" ? DEFAULT_LIGHT_BG : DEFAULT_DARK_BG;
  const bgColor = normalizeHexColor(prefs.bgColor) ?? defaultBg;

  if (prefs.theme === "light") {
    document.documentElement.setAttribute("data-theme", "light");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }

  // Text, hover and muted accent variants are derived from --accent in CSS.
  if (accentColor !== defaultAccent) {
    document.documentElement.style.setProperty("--accent", accentColor);
  } else {
    document.documentElement.style.removeProperty("--accent");
  }

  if (bgColor !== DEFAULT_DARK_BG && bgColor !== DEFAULT_LIGHT_BG) {
    document.documentElement.style.setProperty("--bg-root", bgColor);
  } else {
    document.documentElement.style.removeProperty("--bg-root");
  }

  document
    .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    ?.setAttribute("content", bgColor);
}

export function applyStoredAppearance(): void {
  applyAppearancePreferences(loadAppearancePreferences());
}
