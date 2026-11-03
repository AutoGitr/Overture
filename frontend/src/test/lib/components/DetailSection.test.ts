import { fireEvent, render, screen } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import { expect, it } from "vitest";
import DetailSection from "../../../lib/components/DetailSection.svelte";

const children = createRawSnippet(() => ({ render: () => "<p>Body</p>" }));
const props = { title: "Settings", description: "Defaults.", collapsible: true, children };

it("keeps the user's choice when its default changes", async () => {
  const view = render(DetailSection, { ...props, expanded: true });
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: true }));
  await view.rerender({ ...props, expanded: false });
  await view.rerender({ ...props, expanded: true });
  expect(screen.getByRole("button", { name: "Settings", expanded: false })).toBeInTheDocument();
  expect(screen.getByText("Body")).not.toBeVisible();
});

it("stays open when it is mounted again", async () => {
  const first = render(DetailSection, props);
  await fireEvent.click(screen.getByRole("button", { name: "Settings", expanded: false }));
  first.unmount();
  render(DetailSection, props);
  expect(screen.getByRole("button", { name: "Settings", expanded: true })).toBeInTheDocument();
  expect(screen.getByText("Body")).toBeVisible();
});
