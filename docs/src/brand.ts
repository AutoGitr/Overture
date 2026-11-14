import { useActivePlugin } from "@docusaurus/plugin-content-docs/client";

/** How each project's pages are branded: its name, home page and inline logo's width at 32px. */
export const BRANDS = {
  overture: { name: "Overture", home: "/", logoWidth: 160 },
  overturedb: { name: "OvertureDB", home: "/overturedb", logoWidth: 156 },
} as const;

export type Brand = keyof typeof BRANDS;

/** The project whose pages are open: OvertureDB's docs, or Overture everywhere else. */
export function useBrand(): Brand {
  return useActivePlugin()?.pluginId === "overturedb" ? "overturedb" : "overture";
}
