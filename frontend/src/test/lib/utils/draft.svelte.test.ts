import { describe, expect, it } from "vitest";
import { draftOf } from "../../../lib/utils/draft.svelte";

describe("draftOf", () => {
  it("takes the saved data once it loads and keeps edits through later changes", () => {
    let saved = $state<{ name: string } | null>(null);
    const draft = draftOf(() => saved);
    expect(draft.current).toBeNull();

    saved = { name: "Loaded" };
    expect(draft.current).toEqual({ name: "Loaded" });
    draft.current!.name = "Edited";
    saved = { name: "Refetched" };
    expect(draft.current).toEqual({ name: "Edited" });
    // The draft is a copy: editing it leaves the saved data alone.
    expect(saved).toEqual({ name: "Refetched" });
  });

  it("starts from its initial value and can be replaced", () => {
    const draft = draftOf<{ name: string }>(() => null, { name: "Initial" });
    expect(draft.current).toEqual({ name: "Initial" });

    draft.current = { name: "Saved" };
    draft.current.name = "Saved again";
    expect(draft.current).toEqual({ name: "Saved again" });
  });
});
