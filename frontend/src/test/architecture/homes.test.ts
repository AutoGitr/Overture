/**
 * Each concern of the interface that must stay single has one home, read from
 * the code itself, as `tests/test_architecture/test_homes.py` does for the
 * backend. Code elsewhere reaches it through its home, so a rule about it
 * (a server's colours, how a list chooses everything) holds everywhere by
 * being written once.
 *
 * This guards concerns that must never be written twice; duplication in
 * general is the duplication check's to find.
 */
import { describe, expect, it } from "vitest";

/** Every source of the interface, by its path from `src/`, read as written. */
const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(
    import.meta.glob<string>(["../../app.css", "../../lib/**/*.{svelte,ts,css}"], {
      query: "?raw",
      import: "default",
      eager: true,
    }),
  ).map(([path, source]) => [path.replace(/^\.\.\/\.\.\//, ""), source]),
);

interface Home {
  pattern: RegExp;
  /** The files that may hold the concern, each with why when it is not the home. */
  homes: Record<string, string>;
}

const HOMES: Record<string, Home> = {
  "server colours": {
    pattern: /--server-(plex|jellyfin|emby)\b/,
    homes: { "app.css": "the tokens and the data-server utility" },
  },
  "choosing every option": {
    pattern: /\b(Select|Deselect) (all|every)\b/,
    homes: { "lib/components/SelectAll.svelte": "the control" },
  },
  // Choosing everything sits on the row that names the list, never on a
  // line of its own.
  "where choosing every option sits": {
    pattern: /<SelectAll\b/,
    homes: {
      "lib/components/Checklist.svelte": "beside the list's label",
      "lib/components/JobResultsList.svelte": "beside the count of the findings it chooses",
    },
  },
  "lists of checkboxes": {
    pattern: /\{#each[^}]*\}(?:(?!\{\/each\})[\s\S])*?type="checkbox"/,
    homes: {
      "lib/components/CheckboxList.svelte": "the list",
      "lib/components/ConfirmDialog.svelte":
        "its choices are radios or checkboxes, each with a description",
      "lib/components/GlobalCollectionDefaults.svelte":
        "each Arr service section has its own Search when added switch",
      "lib/components/Schedules.svelte": "each schedule row has its own on switch",
      "lib/components/SourceOrderList.svelte": "each ordered row turns its source on",
      "lib/popups/NotificationsPopup.svelte": "each rule's row holds its own settings",
    },
  },
  // A backend enum's labels come from the generated contracts, as the
  // backend names it in its own messages; only presentation (tones, badges)
  // is the interface's to map.
  "labels of a backend enum": {
    pattern:
      /\w*LABELS\s*:\s*(?:Partial<)?Record<(?:FilterOperator|FilterField|CollectionOrder|ServerAsset|ArtType|AuditStatus|CollectionPosterStyle|ThemeIdSource|ServerType|MediaType|SetDimension|SourceType)\b/,
    homes: {},
  },
  // A field's length is the backend's, read from the generated TEXT_LIMITS.
  "lengths written by hand": {
    pattern: /maxlength=(?:"\d+"|\{\d+\})/,
    homes: { "lib/components/ColorInput.svelte": "a #rrggbb colour is seven characters" },
  },
  "rows a job panel spans": {
    pattern: /grid-row[^;\n]*span/,
    homes: { "lib/components/JobPanel.svelte": "JobPanel.test.ts counts its rows" },
  },
  "native select and datalist": {
    pattern: /<(?:select|datalist)\b/,
    homes: {},
  },
  "dropdown listboxes": {
    pattern: /role="listbox"/,
    homes: { "lib/components/Listbox.svelte": "the floating option list" },
  },
  "combobox controls": {
    pattern: /role="combobox"/,
    homes: {
      "lib/components/Select.svelte": "fixed-choice dropdown",
      "lib/components/SidebarControls.svelte": "ignore `/` shortcut inside comboboxes",
      "lib/components/ValueCombobox.svelte": "searchable and free-text combobox",
    },
  },
};

describe("homes", () => {
  it.each(Object.keys(HOMES))("%s live only in their home", (concern) => {
    const { pattern, homes } = HOMES[concern]!;
    const strays = Object.entries(SOURCES)
      .filter(([name, source]) => !(name in homes) && pattern.test(source))
      .map(([name]) => name);

    expect(
      strays,
      `Reach ${concern} through ${Object.keys(homes).join(", ") || "the generated contracts"}`,
    ).toEqual([]);
    // A home that no longer holds the concern is a stale exception.
    for (const home of Object.keys(homes)) {
      expect(pattern.test(SOURCES[home] ?? ""), `${home} holds no ${concern}`).toBe(true);
    }
  });

  it("finds every source", () => {
    expect(Object.keys(SOURCES)).toContain("lib/components/JobPanel.svelte");
    expect(SOURCES["app.css"]).toContain("--server-plex");
  });
});
