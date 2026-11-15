import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import ArtCard from "../../../lib/components/ArtCard.svelte";
import { artCandidate } from "../../helpers/fixtures";

describe("ArtCard", () => {
  it("names a candidate's source and the OvertureDB poster style it is", () => {
    render(ArtCard, {
      art: artCandidate({ source: "tpdb", poster_style: "matte", width: 2000, height: 3000 }),
    });

    expect(
      screen.getByRole("button", { name: "Use matte poster artwork 2000x3000 from TPDb" }),
    ).toHaveTextContent("TPDb | Matte | 2000x3000");
  });

  it("leaves the source to a grid titled by it", () => {
    render(ArtCard, { art: artCandidate(), showSource: false });

    expect(
      screen.getByRole("button", { name: "Use artwork 1000x1500 from TMDB" }),
    ).toHaveTextContent(/^1000x1500$/);
  });
});
