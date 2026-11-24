import { expect, it } from "vitest";
import { DEFAULT_APP_SETTINGS, POLICY_SETTINGS } from "../../../generated/settings";

/** Where settings are edited: the Settings popup with the components it renders its fields with. */
const SOURCES = import.meta.glob(
  [
    "../../../lib/popups/SettingsPopup.svelte",
    "../../../lib/components/GlobalCollectionDefaults.svelte",
    "../../../lib/components/OvertureDbSettings.svelte",
  ],
  { query: "?raw", import: "default", eager: true },
) as Record<string, string>;

/** The fields of a collection's settings, which the global defaults edit through `POLICY_SETTINGS`. */
const POLICY_SOURCES = import.meta.glob(
  [
    "../../../lib/components/CollectionPolicyFields.svelte",
    "../../../lib/components/CollectionScheduleFields.svelte",
  ],
  { query: "?raw", import: "default", eager: true },
) as Record<string, string>;
const policySource = Object.values(POLICY_SOURCES).join("\n");
/** The global settings a policy field edits, by their policy name. */
const POLICY_FIELDS = new Map(
  Object.entries(POLICY_SETTINGS).map(([name, global]) => [global as string, name]),
);

/** Whether some field of the Settings popup edits *key*. */
function bound(key: string, source: string): boolean {
  // Bound directly, sent by name, named in the policy fields' map, or built
  // from the Arr name.
  const arr = /^(radarr|sonarr)_(.+)$/.exec(key);
  const policy = POLICY_FIELDS.get(key);
  return (
    (policy !== undefined && policySource.includes(`policy.${policy}`)) ||
    new RegExp(`\\bdraft(?:\\.current)?\\.${key}\\b`).test(source) ||
    source.includes(`${key}: `) ||
    source.includes(`"${key}"`) ||
    (arr !== null && source.includes(`\${key}_${arr[2]}`))
  );
}

it("offers a field for every setting the server saves", () => {
  // A setting added on the server fails here until the interface edits it.
  const source = Object.values(SOURCES).join("\n");
  expect(Object.keys(SOURCES)).toHaveLength(3);
  expect(Object.keys(POLICY_SOURCES)).toHaveLength(2);
  const missing = Object.keys(DEFAULT_APP_SETTINGS).filter((key) => !bound(key, source));
  expect(missing).toEqual([]);
});
