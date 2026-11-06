import { fireEvent, render, screen } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import { expect, it } from "vitest";
import { sectionState } from "../../../lib/stores/sectionState.svelte";
import { readJson } from "../../../lib/utils/storage";
import ViewedSection from "../../helpers/ViewedSection.svelte";

const children = createRawSnippet(() => ({ render: () => "<p>Body</p>" }));
const props = {
  view: "collection",
  title: "Settings",
  description: "Defaults.",
  collapsible: true,
  children,
};

it("keeps the user's choice when its default changes", async () => {
  const view = render(ViewedSection, { ...props, expanded: true });
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: true }));
  await view.rerender({ ...props, expanded: false });
  await view.rerender({ ...props, expanded: true });
  expect(screen.getByRole("button", { name: "Settings", expanded: false })).toBeInTheDocument();
  expect(screen.getByText("Body")).not.toBeVisible();
});

it("stays open when it is mounted again", async () => {
  const first = render(ViewedSection, props);
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: false }));
  first.unmount();
  render(ViewedSection, props);
  expect(screen.getByRole("button", { name: "Settings", expanded: true })).toBeInTheDocument();
  expect(screen.getByText("Body")).toBeVisible();
});

it("keeps each view's choice apart", async () => {
  render(ViewedSection, props);
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: false }));
  render(ViewedSection, { ...props, view: "collection-groups" });
  expect(screen.getAllByRole("button", { name: "Settings" }).map((b) => b.ariaExpanded)).toEqual([
    "true",
    "false",
  ]);
});

it("starts a view over when it is forgotten, and persists only remembered views", async () => {
  const first = render(ViewedSection, props);
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: false }));
  first.unmount();
  sectionState.forget("collection");
  const again = render(ViewedSection, props);
  expect(screen.getByRole("button", { name: "Settings", expanded: false })).toBeInTheDocument();
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: false }));
  again.unmount();
  expect(readJson("sections_open_by_view", {})).toEqual({});

  render(ViewedSection, { ...props, view: "collection-groups" });
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: false }));
  expect(readJson("sections_open_by_view", {})).toEqual({});
});

it("persists the filters' sections", async () => {
  render(ViewedSection, { ...props, view: "filters" });
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: false }));
  expect(readJson("sections_open_by_view", {})).toEqual({ "filters/Settings": true });
});
