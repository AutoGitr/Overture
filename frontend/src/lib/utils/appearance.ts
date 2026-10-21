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

type ThemeMode = AppearancePreferences["theme"];

/** Each mode's own colours, used wherever a colour is unset or invalid. */
const THEME_COLORS = {
  dark: { accentColor: DEFAULT_ACCENT, bgColor: DEFAULT_DARK_BG },
  light: { accentColor: DEFAULT_LIGHT_ACCENT, bgColor: DEFAULT_LIGHT_BG },
} as const satisfies Record<ThemeMode, Pick<AppearancePreferences, "accentColor" | "bgColor">>;

export const DEFAULT_APPEARANCE: AppearancePreferences = {
  theme: "dark",
  ...THEME_COLORS.dark,
  showBackgroundImage: true,
};

/** The preferences in another mode: its background, and its accent unless one was picked. */
export function withThemeMode(
  prefs: AppearancePreferences,
  theme: ThemeMode,
): AppearancePreferences {
  const pickedAccent = !Object.values(THEME_COLORS).some(
    (colors) => colors.accentColor === prefs.accentColor,
  );
  return {
    ...prefs,
    theme,
    bgColor: THEME_COLORS[theme].bgColor,
    accentColor: pickedAccent ? prefs.accentColor : THEME_COLORS[theme].accentColor,
  };
}

/** The colours to show, each replaced by the mode's own when it is not a valid hex colour. */
function resolvedColors({
  theme,
  accentColor,
  bgColor,
}: Pick<AppearancePreferences, "theme" | "accentColor" | "bgColor">) {
  const defaults = THEME_COLORS[theme];
  return {
    accentColor: normalizeHexColor(accentColor) ?? defaults.accentColor,
    bgColor: normalizeHexColor(bgColor) ?? defaults.bgColor,
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
  const defaults = THEME_COLORS[theme];
  return {
    theme,
    ...resolvedColors({
      theme,
      accentColor: readJson<string>("accentColor", defaults.accentColor),
      bgColor: readJson<string>("bgColor", defaults.bgColor),
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
  const defaultAccent = THEME_COLORS[prefs.theme].accentColor;

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
