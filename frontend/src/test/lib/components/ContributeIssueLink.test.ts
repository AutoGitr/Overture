import { render, screen } from "@testing-library/svelte";
import { expect, it } from "vitest";
import ContributeIssueLink from "../../../lib/components/ContributeIssueLink.svelte";

it("links the filled-in issue by GitHub's logo and says what is left to do", () => {
  render(ContributeIssueLink, {
    issue: {
      url: "https://github.com/o/r/issues/new?template=movie.yml",
      reason: null,
      notes: ["Tick No theme"],
    },
  });
  const link = screen.getByRole("link", { name: "GitHub" });
  expect(link).toHaveAttribute("href", "https://github.com/o/r/issues/new?template=movie.yml");
  expect(link).toHaveAttribute("title", "Contribute to OvertureDB on GitHub\nTick No theme");
});

it("shows nothing when there is nothing to contribute", () => {
  render(ContributeIssueLink, {
    issue: { url: null, reason: "Nothing is selected to contribute", notes: [] },
  });
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
