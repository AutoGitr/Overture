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
  choices: ["complete", "partial", "missing"],
};

describe("CustomFilterCard", () => {
  beforeEach(() => queryClient.clear());

  it("saves a new filter of a status field and applies it", async () => {
    const stored: SavedFilterRead[] = [];
    const { calls } = mockFetchRoutes({
      "/api/library/filters/capabilities": { fields: [unarted], sources: [] },
      "/api/library/filters/saved": (call: { init: RequestInit }) => {
        if (call.init.method !== "POST") return Response.json(stored);
        const body = JSON.parse(String(call.init.body)) as Omit<SavedFilterRead, "id">;
        stored.push({ ...body, id: 7 });
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
});
