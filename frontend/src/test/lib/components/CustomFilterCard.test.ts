import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import type {
  CollectionFieldRead,
  MediaType,
  SavedFilterRead,
} from "../../../generated/rest/types.gen";
import CustomFilterCard from "../../../lib/components/CustomFilterCard.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { mockFetchRoutes } from "../../helpers/fetch";
import { renderWithQueryClient } from "../../helpers/render";

const unarted: CollectionFieldRead = {
  field: "art_status",
  label: "Art status",
  kind: "tag",
  operators: ["is", "is_not"],
  smart_operators: [],
  local: true,
  smart: false,
  labelled: false,
  library_status: true,
  choices: [
    { value: "complete", label: "Complete" },
    { value: "partial", label: "Partial" },
    { value: "missing", label: "Missing" },
  ],
  free_values: false,
  by_id: false,
  ignores_case: true,
};

describe("CustomFilterCard", () => {
  beforeEach(() => queryClient.clear());

  it("saves a new filter of a status field and applies it", async () => {
    const stored: SavedFilterRead[] = [];
    const { calls } = mockFetchRoutes({
      "/api/library/filters/capabilities": { fields: [unarted], sources: [] },
      "/api/library/filters/saved": (call: { init: RequestInit }) => {
        if (call.init.method !== "POST") return Response.json(stored);
        const body = JSON.parse(String(call.init.body)) as Pick<
          SavedFilterRead,
          "name" | "criteria"
        >;
        stored.push({
          ...body,
          id: 7,
          media_type: null,
          media_types: ["movie", "show"],
          unavailable: {},
        });
        return Response.json(stored[0]);
      },
    });
    const props: { filterId: number | null; mediaType: MediaType } = {
      filterId: null,
      mediaType: "movie",
    };
    renderWithQueryClient(CustomFilterCard, props);

    await fireEvent.click(await screen.findByRole("button", { name: "New" }));
    await fireEvent.input(screen.getByLabelText("Name"), { target: { value: "Unarted" } });
    await fireEvent.click(await screen.findByRole("button", { name: /Condition/ }));
    await fireEvent.click(screen.getByRole("button", { name: "Save filter" }));

    await waitFor(() => expect(props.filterId).toBe(7));
    const created = calls.find((call) => call.init.method === "POST");
    expect(JSON.parse(String(created?.init.body))).toMatchObject({
      name: "Unarted",
      media_type: "movie",
      criteria: { conditions: [{ field: "art_status", operator: "is", value: "complete" }] },
    });
    await fireEvent.click(screen.getByLabelText("Saved filter"));
    expect(await screen.findByRole("option", { name: "Unarted" })).toBeInTheDocument();
  });

  it("offers the values of every library, as the filter tests them all", async () => {
    const collection: CollectionFieldRead = {
      ...unarted,
      field: "collection",
      label: "Collection",
      library_status: false,
      choices: [],
      by_id: true,
      ignores_case: false,
    };
    const { calls } = mockFetchRoutes({
      "/api/library/filters/capabilities": { fields: [collection], sources: [] },
      "/api/library/filters/saved": [],
      "/api/collections/field-values": [{ value: "4", label: "Requests", count: 62 }],
    });
    renderWithQueryClient(CustomFilterCard, { filterId: null, mediaType: "movie" });

    await fireEvent.click(await screen.findByRole("button", { name: "New" }));
    await fireEvent.click(await screen.findByRole("button", { name: /Condition/ }));
    await fireEvent.focus(
      screen.getByRole("combobox", { name: "Custom filter conditions condition 1 value" }),
    );

    expect(await screen.findByRole("option", { name: /^Requests/ })).toBeInTheDocument();
    const asked = calls.find((call) => call.url.startsWith("/api/collections/field-values"));
    expect(asked?.url).not.toContain("library_id");
  });

  it("offers only the saved filters that suit the media type, and says where the rest are", async () => {
    const filter = (id: number, name: string, media_types: MediaType[]): SavedFilterRead => ({
      id,
      name,
      criteria: { mode: "all", conditions: [], groups: [] },
      media_type: null,
      media_types,
      unavailable: {},
    });
    mockFetchRoutes({
      "/api/library/filters/saved": [
        filter(1, "Shared", ["movie", "show"]),
        filter(2, "Seasons", ["show"]),
      ],
    });
    renderWithQueryClient(CustomFilterCard, { filterId: null, mediaType: "movie" });

    await fireEvent.click(screen.getByLabelText("Saved filter"));
    expect(await screen.findByRole("option", { name: "Shared" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Seasons" })).toBeNull();
    expect(
      screen.getByText(/One saved filter tests what movies lack, so the Shows tab offers it/),
    ).toBeInTheDocument();
  });

  it("shows a chosen filter's criteria at once, ready to change and save", async () => {
    const shared: SavedFilterRead = {
      id: 1,
      name: "Unarted",
      criteria: {
        mode: "all",
        conditions: [{ kind: "field", field: "art_status", operator: "is", value: "missing" }],
        groups: [],
      },
      media_type: null,
      media_types: ["movie", "show"],
      unavailable: {},
    };
    const { calls } = mockFetchRoutes({
      "/api/library/filters/capabilities": { fields: [unarted], sources: [] },
      "/api/library/filters/saved": [shared],
      "/api/library/filters/saved/1": (call: { init: RequestInit }) =>
        Response.json({ ...shared, ...JSON.parse(String(call.init.body)) }),
    });
    renderWithQueryClient(CustomFilterCard, { filterId: 1, mediaType: "movie" });

    // No Edit step: the chosen filter's name and conditions show as they are.
    expect(await screen.findByLabelText("Name")).toHaveValue("Unarted");
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.getByRole("button", { name: "Save filter" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Discard changes" })).toBeNull();

    await fireEvent.input(screen.getByLabelText("Name"), { target: { value: "No art" } });
    await fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Unarted");

    await fireEvent.input(screen.getByLabelText("Name"), { target: { value: "No art" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save filter" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "PUT")).toBe(true));
    const updated = calls.find((call) => call.init.method === "PUT");
    expect(JSON.parse(String(updated?.init.body))).toMatchObject({ name: "No art" });
  });
});
