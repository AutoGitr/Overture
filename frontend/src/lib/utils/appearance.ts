import { readJson, writeJson } from "./storage";

export interface AppearancePreferences {
  theme: "dark" | "light";
  accentColor: string;
  bgColor: string;
  showBackgroundImage: boolean;
}

export const DEFAULT_DARK_BG = "#0a0c10";
export const DEFAULT_LIGHT_BG = "#f3f4f6";
/** One accent for both modes: the stylesheet darkens it on light surfaces. */
export const DEFAULT_ACCENT = "#d8c7a3";

type ThemeMode = AppearancePreferences["theme"];

/** Each mode's own background, used wherever none is set or it is invalid. */
const DEFAULT_BACKGROUNDS: Record<ThemeMode, string> = {
  dark: DEFAULT_DARK_BG,
  light: DEFAULT_LIGHT_BG,
};

export const DEFAULT_APPEARANCE: AppearancePreferences = {
  theme: "dark",
  accentColor: DEFAULT_ACCENT,
  bgColor: DEFAULT_DARK_BG,
  showBackgroundImage: true,
};

/** The preferences in another mode, with that mode's background. */
export function withThemeMode(
  prefs: AppearancePreferences,
  theme: ThemeMode,
): AppearancePreferences {
  return { ...prefs, theme, bgColor: DEFAULT_BACKGROUNDS[theme] };
}

/** The colours to show, each replaced by its default when it is not a valid hex colour. */
function resolvedColors({
  theme,
  accentColor,
  bgColor,
}: Pick<AppearancePreferences, "theme" | "accentColor" | "bgColor">) {
  return {
    accentColor: normalizeHexColor(accentColor) ?? DEFAULT_ACCENT,
    bgColor: normalizeHexColor(bgColor) ?? DEFAULT_BACKGROUNDS[theme],
  };
}

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
  return {
    theme,
    ...resolvedColors({
      theme,
      accentColor: readJson<string>("accentColor", DEFAULT_ACCENT),
      bgColor: readJson<string>("bgColor", DEFAULT_BACKGROUNDS[theme]),
    }),
    showBackgroundImage: readJson("showBackgroundImage", true),
  };
}

export function saveAppearancePreferences(prefs: AppearancePreferences): void {
  const { accentColor, bgColor } = resolvedColors(prefs);
  writeJson("theme", prefs.theme);
  writeJson("accentColor", accentColor);
  writeJson("bgColor", bgColor);
  writeJson("showBackgroundImage", prefs.showBackgroundImage);
}

export function applyAppearancePreferences(prefs: AppearancePreferences): void {
  const { accentColor, bgColor } = resolvedColors(prefs);

  if (prefs.theme === "light") {
    document.documentElement.setAttribute("data-theme", "light");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }

  // The mode's lightness, and the text, hover and muted variants, are derived in CSS.
  if (accentColor !== DEFAULT_ACCENT) {
    document.documentElement.style.setProperty("--accent-color", accentColor);
  } else {
    document.documentElement.style.removeProperty("--accent-color");
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
