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
    const props: { filterId: number | null; mediaType: MediaType; libraryId: string } = {
      filterId: null,
      mediaType: "movie",
      libraryId: "movies",
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
    expect(await screen.findByRole("option", { name: "Unarted" })).toBeInTheDocument();
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
    renderWithQueryClient(CustomFilterCard, { filterId: null, mediaType: "movie", libraryId: "m" });

    expect(await screen.findByRole("option", { name: "Shared" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Seasons" })).toBeNull();
    expect(
      screen.getByText(/One saved filter tests what movies lack, so the Shows tab offers it/),
    ).toBeInTheDocument();
  });
});
