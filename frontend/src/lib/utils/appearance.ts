import { readJson, writeJson } from "./storage";

export type ThemeMode = "system" | "dark" | "light";
export type ContrastMode = "standard" | "more";

export interface AppearancePreferences {
  /** "system" follows the device and changes with it. */
  theme: ThemeMode;
  contrast: ContrastMode;
  accentColor: string;
  showBackgroundImage: boolean;
}

/** One accent for both modes: the stylesheet darkens its text on light surfaces. */
export const DEFAULT_ACCENT = "#d8c7a3";

export const DEFAULT_APPEARANCE: AppearancePreferences = {
  theme: "system",
  contrast: "standard",
  accentColor: DEFAULT_ACCENT,
  showBackgroundImage: true,
};

const THEME_MODES: readonly ThemeMode[] = ["system", "dark", "light"];
export const DARK_QUERY = "(prefers-color-scheme: dark)";

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

/** The mode a theme shows now: the device's own for "system". */
export function resolvedTheme(theme: ThemeMode): "dark" | "light" {
  if (theme !== "system") return theme;
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

export function loadAppearancePreferences(): AppearancePreferences {
  const theme = readJson<string>("theme", DEFAULT_APPEARANCE.theme);
  return {
    theme: THEME_MODES.find((mode) => mode === theme) ?? DEFAULT_APPEARANCE.theme,
    contrast: readJson<string>("contrast", "standard") === "more" ? "more" : "standard",
    accentColor:
      normalizeHexColor(readJson<string>("accentColor", DEFAULT_ACCENT)) ?? DEFAULT_ACCENT,
    showBackgroundImage: readJson("showBackgroundImage", true),
  };
}

export function saveAppearancePreferences(prefs: AppearancePreferences): void {
  writeJson("theme", prefs.theme);
  writeJson("contrast", prefs.contrast);
  writeJson("accentColor", normalizeHexColor(prefs.accentColor) ?? DEFAULT_ACCENT);
  writeJson("showBackgroundImage", prefs.showBackgroundImage);
}

export function applyAppearancePreferences(prefs: AppearancePreferences): void {
  const root = document.documentElement;
  root.dataset.theme = resolvedTheme(prefs.theme);
  if (prefs.contrast === "more") root.dataset.contrast = "more";
  else delete root.dataset.contrast;

  // The mode's text, hover and muted variants are derived in CSS.
  const accentColor = normalizeHexColor(prefs.accentColor) ?? DEFAULT_ACCENT;
  if (accentColor !== DEFAULT_ACCENT) root.style.setProperty("--accent-color", accentColor);
  else root.style.removeProperty("--accent-color");

  document
    .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    ?.setAttribute("content", getComputedStyle(document.body).backgroundColor);
}

export function applyStoredAppearance(): void {
  applyAppearancePreferences(loadAppearancePreferences());
}
