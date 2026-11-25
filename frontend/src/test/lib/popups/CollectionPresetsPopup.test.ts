import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getLibrariesOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import type { CollectionPresetFileInput } from "../../../generated/rest/types.gen";
import PresetImport from "../../../lib/components/PresetImport.svelte";
import CollectionPresetsPopup from "../../../lib/popups/CollectionPresetsPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { mockFetchRoutes, type FetchCall } from "../../helpers/fetch";
import { renderWithQueryClient } from "../../helpers/render";

const LIBRARIES = [
  { id: "1:movies", title: "Movies", media_type: "movie" as const, server_id: 1, count: 3 },
  { id: "1:kids", title: "Kids Movies", media_type: "movie" as const, server_id: 1, count: 1 },
  { id: "1:shows", title: "Shows", media_type: "show" as const, server_id: 1, count: 2 },
];

const FILE: CollectionPresetFileInput = {
  preset_version: 1,
  groups: [{ name: "Decades", generator: { dimension: "decade", media_types: ["movie"] } }],
  collections: [
    {
      title: "Christmas",
      criteria: {
        show: {
          mode: "all",
          conditions: [{ kind: "field", field: "genre", operator: "is", value: "Holiday" }],
        },
      },
    },
  ],
};

function body(call: FetchCall): unknown {
  return JSON.parse(String(call.init.body));
}

describe("PresetImport", () => {
  beforeEach(() => queryClient.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("previews a file in a library of each of its media types, then adds it", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/presets/plan": {
        items: [
          { kind: "group", name: "Decades", status: "add", chosen: true },
          {
            kind: "collection",
            name: "Christmas",
            status: "refused",
            reason: "Title taken",
            chosen: true,
          },
        ],
        warnings: ["Set up tmdb for every collection to find its titles"],
      },
      "/api/collections/presets/import": {
        items: [{ kind: "group", name: "Decades", status: "add", chosen: true }],
        collection_ids: [],
      },
    });
    renderWithQueryClient(PresetImport, { file: FILE, libraries: LIBRARIES });

    expect(screen.getByRole("combobox", { name: "Library for movies" })).toHaveTextContent(
      "Movies",
    );
    expect(screen.getByRole("combobox", { name: "Library for shows" })).toHaveTextContent("Shows");
    await fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    const plan = await screen.findByRole("list", { name: "What adding does" });
    expect(within(plan).getByText("Group Decades")).toBeInTheDocument();
    expect(within(plan).getByText("Title taken")).toBeInTheDocument();
    expect(
      screen.getByText("Set up tmdb for every collection to find its titles"),
    ).toBeInTheDocument();
    expect(body(calls[0]!)).toEqual({
      file: FILE,
      libraries: { movie: ["1:movies"], show: ["1:shows"] },
    });

    await fireEvent.click(screen.getByRole("button", { name: "Add" }));
    const added = await screen.findByRole("list", { name: "What was added" });
    expect(within(added).getByText("Added")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
  });

  it("adds to the library chosen for a media type", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/presets/plan": { items: [], warnings: [] },
    });
    renderWithQueryClient(PresetImport, { file: FILE, libraries: LIBRARIES });

    await fireEvent.click(screen.getByRole("combobox", { name: "Library for movies" }));
    await fireEvent.click(screen.getByRole("option", { name: "Kids Movies" }));
    await fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(body(calls[0]!)).toMatchObject({ libraries: { movie: ["1:kids"] } });
  });
});

describe("PresetImport updates", () => {
  beforeEach(() => queryClient.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("updates what a preset added unless it is unticked", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/presets/plan": {
        items: [
          {
            kind: "collection",
            name: "Christmas",
            status: "update",
            reason: "Takes the preset's new criteria and settings, replacing changes made here",
            chosen: true,
          },
          { kind: "collection", name: "Easter", status: "add", chosen: true },
        ],
        warnings: [],
      },
      "/api/collections/presets/import": {
        items: [
          { kind: "collection", name: "Christmas", status: "skip", chosen: true },
          { kind: "collection", name: "Easter", status: "add", chosen: true },
        ],
        collection_ids: [9],
      },
    });
    renderWithQueryClient(PresetImport, { file: FILE, libraries: LIBRARIES });

    await fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    const plan = await screen.findByRole("list", { name: "What adding does" });
    expect(within(plan).getByText("Updates")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Collection Christmas" }));
    await fireEvent.click(screen.getByRole("button", { name: "Add" }));

    const added = await screen.findByRole("list", { name: "What was added" });
    expect(within(added).getByText("Skipped")).toBeInTheDocument();
    const imported = calls.find((call) => call.url.endsWith("/presets/import"));
    expect(body(imported!)).toMatchObject({ skip: ["Christmas"] });
  });

  it("starts with what was deleted since unticked", async () => {
    mockFetchRoutes({
      "/api/collections/presets/plan": {
        items: [
          {
            kind: "collection",
            name: "Christmas",
            status: "add",
            reason: "Deleted here since the preset added it",
            chosen: false,
          },
          { kind: "collection", name: "Easter", status: "add", chosen: true },
        ],
        warnings: [],
      },
    });
    renderWithQueryClient(PresetImport, { file: FILE, libraries: LIBRARIES });

    await fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByRole("checkbox", { name: "Collection Christmas" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Collection Easter" })).toBeChecked();
  });

  it("adds nothing once every item is unticked", async () => {
    mockFetchRoutes({
      "/api/collections/presets/plan": {
        items: [{ kind: "group", name: "Decades", status: "add", chosen: true }],
        warnings: [],
      },
    });
    renderWithQueryClient(PresetImport, { file: FILE, libraries: LIBRARIES });

    await fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await fireEvent.click(await screen.findByRole("checkbox", { name: "Group Decades" }));
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });
});

describe("CollectionPresetsPopup", () => {
  beforeEach(() => {
    queryClient.clear();
    queryClient.setQueryData(getLibrariesOptions().queryKey, LIBRARIES);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("lists OvertureDB's presets with what keeps one from being added", async () => {
    const gallery = {
      generated_at: "2026-11-01T00:00:00Z",
      presets: [
        {
          id: "holidays",
          preset: {
            id: "holidays",
            title: "Holidays",
            description: "Holiday titles.",
            category: "seasonal",
            tags: [],
            media_types: ["show"],
          },
          file: FILE,
          unavailable: ["tmdb"],
        },
        { id: "newer", problem: "Needs a newer version of Overture" },
        {
          id: "decades",
          preset: {
            id: "decades",
            title: "Decades",
            description: "One per decade.",
            category: "decades",
            tags: [],
            media_types: ["movie"],
          },
          file: FILE,
          added_at: "2026-11-20T00:00:00Z",
          changes: ["Changes Decades"],
        },
        {
          id: "genres",
          preset: {
            id: "genres",
            title: "Genres",
            description: "One per genre.",
            category: "genres",
            tags: [],
            media_types: ["movie"],
          },
          file: FILE,
          added_at: "2026-11-20T00:00:00Z",
          changes: [],
        },
      ],
    };
    mockFetchRoutes({
      "/api/collections/presets": gallery,
      "/api/collections/presets/plan": { items: [], warnings: [] },
    });
    renderWithQueryClient(CollectionPresetsPopup);

    expect(await screen.findByText("Holiday titles.")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "OvertureDB presets" });
    expect(within(list).getByText("Needs tmdb")).toBeInTheDocument();
    expect(within(list).getByText("Needs a newer version of Overture")).toBeInTheDocument();
    const [add, unreadable] = within(list).getAllByRole("button", { name: "Add…" });
    expect(unreadable).toBeDisabled();
    expect(within(list).getByText("Newer version")).toBeInTheDocument();
    expect(
      within(list).getByRole("list", { name: "What the newer version changes" }),
    ).toHaveTextContent("Changes Decades");
    expect(within(list).getByRole("button", { name: "Update…" })).toBeInTheDocument();
    expect(within(list).getByText("Added")).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "Add again…" })).toBeInTheDocument();

    await fireEvent.click(add!);
    expect(screen.getByRole("heading", { name: "Holidays" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Back to presets" }));
    expect(screen.getByRole("list", { name: "OvertureDB presets" })).toBeInTheDocument();
  });

  it("exports chosen groups and offers the file to OvertureDB", async () => {
    const createObjectURL = vi.fn(() => "blob:file");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
    const { calls } = mockFetchRoutes({
      "/api/collections/presets": { presets: [] },
      "/api/collections/groups": ["Decades", "Ungrouped"],
      "/api/collections": [],
      "/api/collections/presets/export": {
        file: FILE,
        refused: [{ title: "Local", reason: "It tests folder, which only this install has" }],
        warnings: [],
        issue: {
          url: "https://github.com/AutoGitr/OvertureDB/issues/new?template=preset.yml",
          notes: [],
        },
      },
    });
    renderWithQueryClient(CollectionPresetsPopup);

    await fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    const exportButton = screen.getByRole("button", { name: "Export" });
    expect(exportButton).toBeDisabled();
    await fireEvent.click(await screen.findByRole("checkbox", { name: "Decades" }));
    await fireEvent.click(exportButton);

    expect(
      await screen.findByText("Left out Local: It tests folder, which only this install has"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /GitHub/ })).toHaveAttribute(
      "href",
      "https://github.com/AutoGitr/OvertureDB/issues/new?template=preset.yml",
    );
    const exported = calls.find((call) => call.url.endsWith("/presets/export"));
    expect(body(exported!)).toEqual({ groups: ["Decades"], collection_ids: null });
    expect(createObjectURL).toHaveBeenCalledOnce();
  });

  it("refuses a file that is not an export", async () => {
    mockFetchRoutes({ "/api/collections/presets": { presets: [] } });
    renderWithQueryClient(CollectionPresetsPopup);

    await fireEvent.click(screen.getByRole("tab", { name: "Import file" }));
    const input = screen.getByLabelText("Collections file");
    await fireEvent.change(input, {
      target: { files: [new File(["not json"], "notes.txt", { type: "text/plain" })] },
    });

    expect(
      await screen.findByText("notes.txt is not a collections file exported from Overture"),
    ).toBeInTheDocument();
  });
});
