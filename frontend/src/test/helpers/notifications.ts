import { fireEvent, screen, within } from "@testing-library/svelte";
import { vi } from "vitest";
import { notificationState } from "../../lib/stores/notificationState.svelte";

/** Answer the open confirmation dialog, picking the `choice` labelled so first, and return what it asked. */
export async function answerConfirmation(confirmed: boolean, choice?: string) {
  const request = await vi.waitFor(() => {
    const pending = notificationState.confirmRequest;
    if (!pending) throw new Error("No confirmation was requested.");
    return { ...pending };
  });
  const dialog = screen.getByRole("dialog", { name: request.title });
  if (choice) await fireEvent.click(within(dialog).getByRole("radio", { name: choice }));
  const label = confirmed ? (request.confirmLabel ?? "Confirm") : "Cancel";
  await fireEvent.click(within(dialog).getByRole("button", { name: label }));
  return request;
}
