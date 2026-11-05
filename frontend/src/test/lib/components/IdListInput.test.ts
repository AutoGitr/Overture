import { fireEvent, render, screen } from "@testing-library/svelte";
import { expect, it, vi } from "vitest";
import IdListInput from "../../../lib/components/IdListInput.svelte";

const props = { label: "TMDB IDs", placeholder: "IDs" };

it("keeps what was typed when an entry is not an ID, and names it", async () => {
  const onchange = vi.fn();
  render(IdListInput, { ...props, ids: [], onchange });
  const input = screen.getByLabelText<HTMLInputElement>("TMDB IDs");
  await fireEvent.input(input, { target: { value: "550, Fight Club" } });
  await fireEvent.change(input);
  expect(onchange).not.toHaveBeenCalled();
  expect(input).toHaveValue("550, Fight Club");
  expect(input.validationMessage).toBe("Not a TMDB ID or link: Fight Club");
});

it("takes IDs and TMDB links", async () => {
  const onchange = vi.fn();
  render(IdListInput, { ...props, ids: [], onchange });
  const input = screen.getByLabelText<HTMLInputElement>("TMDB IDs");
  await fireEvent.input(input, {
    target: { value: "550, https://www.themoviedb.org/movie/680-pulp-fiction" },
  });
  await fireEvent.change(input);
  expect(onchange).toHaveBeenCalledWith([550, 680]);
  expect(input.validationMessage).toBe("");
});
