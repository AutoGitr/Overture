import { expect, it } from "vitest";
import { DEFAULT_APP_SETTINGS } from "../../../generated/settings";

/** Where settings are edited: the Settings popup with the components it renders its fields with. */
const SOURCES = import.meta.glob(
  [
    "../../../lib/popups/SettingsPopup.svelte",
    "../../../lib/components/GlobalCollectionDefaults.svelte",
    "../../../lib/components/OvertureDbSettings.svelte",
  ],
  { query: "?raw", import: "default", eager: true },
) as Record<string, string>;

/** Whether some field of the Settings popup edits *key*. */
function bound(key: string, source: string): boolean {
  // Bound directly, sent by name, named in the policy fields' map, or built
  // from the Arr name.
  const arr = /^(radarr|sonarr)_(.+)$/.exec(key);
  return (
    source.includes(`draft.${key}`) ||
    source.includes(`${key}: `) ||
    source.includes(`"${key}"`) ||
    (arr !== null && source.includes(`\${key}_${arr[2]}`))
  );
}

it("offers a field for every setting the server saves", () => {
  // A setting added on the server fails here until the interface edits it.
  const source = Object.values(SOURCES).join("\n");
  expect(Object.keys(SOURCES)).toHaveLength(3);
  const missing = Object.keys(DEFAULT_APP_SETTINGS).filter((key) => !bound(key, source));
  expect(missing).toEqual([]);
});
