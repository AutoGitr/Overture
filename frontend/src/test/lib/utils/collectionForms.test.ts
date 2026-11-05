import { describe, expect, it } from "vitest";
import { defaultGenerator, withDimension } from "../../../lib/utils/collectionForms.svelte";
import { dimension } from "../../helpers/fixtures";

describe("withDimension", () => {
  const genres = dimension({ dimension: "genre", label: "Genres" });
  const editions = dimension({ dimension: "edition", label: "Editions", smart_only: true });

  it("keeps the user's Most common only and adds no limit of its own", () => {
    const chosen = withDimension({ ...defaultGenerator(), top: 10 }, genres, undefined);
    expect(chosen.top).toBe(10);
    expect(withDimension(defaultGenerator(), genres, undefined).top).toBeNull();
  });

  it("makes a set smart for a dimension only Plex counts, and back when it leaves one", () => {
    const smart = withDimension(defaultGenerator(), editions, genres);
    expect(smart.smart).toBe(true);
    expect(withDimension(smart, genres, editions).smart).toBe(false);
    // A smart set the user chose stays smart.
    expect(withDimension({ ...defaultGenerator(), smart: true }, genres, genres).smart).toBe(true);
  });
});
