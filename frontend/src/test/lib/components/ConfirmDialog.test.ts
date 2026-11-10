import { fireEvent, screen, within } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { chooseAction, selectActions } from "../../../lib/stores/notificationState.svelte";

const choices = [
  { value: "forget", label: "Forget" },
  { value: "file", label: "Delete the file" },
  { value: "server", label: "Delete from the server", unavailable: "The server cannot" },
];

describe("ConfirmDialog", () => {
  it("combines ticked choices, starting from those the request ticks", async () => {
    const chosen = selectActions({
      title: "Remove?",
      message: "Pick.",
      choices,
      initial: ["forget"],
    });
    const dialog = await screen.findByRole("dialog", { name: "Remove?" });
    const forget = within(dialog).getByRole("checkbox", { name: "Forget" });
    expect(forget).toBeChecked();
    expect(within(dialog).getByRole("checkbox", { name: "Delete from the server" })).toBeDisabled();
    expect(within(dialog).getByText("The server cannot")).toBeInTheDocument();

    await fireEvent.click(within(dialog).getByRole("checkbox", { name: "Delete the file" }));
    await fireEvent.click(forget);
    await fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    await expect(chosen).resolves.toEqual(["file"]);
  });

  it("asks for at least one ticked choice", async () => {
    void selectActions({ title: "Remove?", message: "Pick.", choices });
    const dialog = await screen.findByRole("dialog", { name: "Remove?" });

    expect(within(dialog).getByRole("button", { name: "Confirm" })).toBeDisabled();
  });

  it("picks exactly one choice and resolves null on cancel", async () => {
    const picked = chooseAction({ title: "Where?", message: "Pick.", choices });
    let dialog = await screen.findByRole("dialog", { name: "Where?" });
    await fireEvent.click(within(dialog).getByRole("radio", { name: "Forget" }));
    await fireEvent.click(within(dialog).getByRole("radio", { name: "Delete the file" }));
    await fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await expect(picked).resolves.toBe("file");

    const cancelled = chooseAction({ title: "Again?", message: "Pick.", choices });
    dialog = await screen.findByRole("dialog", { name: "Again?" });
    await fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await expect(cancelled).resolves.toBeNull();
    expect(screen.queryByRole("dialog", { name: "Again?" })).not.toBeInTheDocument();
  });
});
