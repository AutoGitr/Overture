import { fireEvent, render, screen } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import { expect, it } from "vitest";
import { configureSections, SectionView } from "../../../lib/stores/sectionState.svelte";
import { readJson } from "../../../lib/utils/storage";
import ViewedSection from "../../helpers/ViewedSection.svelte";

const children = createRawSnippet(() => ({ render: () => "<p>Body</p>" }));
const props = {
  title: "Settings",
  description: "Defaults.",
  collapsible: true,
  children,
};

it("opens a collection's Setup and Content and closes every other section", () => {
  const view = configureSections();
  const titles = ["Setup", "Content", "Members", "Settings", "Active dates", "Missing"];
  for (const title of titles) render(ViewedSection, { ...props, title, view });
  expect(
    titles.map((name) => screen.getByRole("button", { name }).getAttribute("aria-expanded")),
  ).toEqual(["true", "true", "false", "false", "false", "false"]);
});

it("keeps the choice made in its view when it is mounted again", async () => {
  const view = configureSections();
  const first = render(ViewedSection, { ...props, view });
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: false }));
  first.unmount();
  render(ViewedSection, { ...props, view });
  expect(screen.getByRole("button", { name: "Settings", expanded: true })).toBeInTheDocument();
  expect(screen.getByText("Body")).toBeVisible();
});

it("starts every new view over, and stores nothing for it", async () => {
  const first = render(ViewedSection, { ...props, view: configureSections() });
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: false }));
  first.unmount();
  render(ViewedSection, { ...props, view: configureSections() });
  expect(screen.getByRole("button", { name: "Settings", expanded: false })).toBeInTheDocument();
  expect(readJson("sections_open_by_view", {})).toEqual({});
});

it("keeps a remembered view's choices across visits", async () => {
  const first = render(ViewedSection, { ...props, view: new SectionView(() => true, "filters") });
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: true }));
  expect(readJson("sections_open_by_view", {})).toEqual({ "filters/Settings": false });
  first.unmount();
  render(ViewedSection, { ...props, view: new SectionView(() => true, "filters") });
  expect(screen.getByRole("button", { name: "Settings", expanded: false })).toBeInTheDocument();
});
