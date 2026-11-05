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

it("starts each collection over, and remembers only views meant to be remembered", async () => {
  const first = render(ViewedSection, { ...props, view: "collection:1" });
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: false }));
  first.unmount();
  // The same collection remounted, by a refetch say, keeps the choice.
  const again = render(ViewedSection, { ...props, view: "collection:1" });
  expect(screen.getByRole("button", { name: "Settings", expanded: true })).toBeInTheDocument();
  again.unmount();
  sectionState.enter("collection:2");
  render(ViewedSection, { ...props, view: "collection:2" });
  expect(screen.getByRole("button", { name: "Settings", expanded: false })).toBeInTheDocument();
  sectionState.enter("collection:1");
  expect(sectionState.isOpen("collection:1", "Settings", false)).toBe(false);
  expect(readJson("sections_open_by_view", {})).toEqual({});
});
