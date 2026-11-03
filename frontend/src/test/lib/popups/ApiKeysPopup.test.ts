import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, expect, it } from "vitest";
import ApiKeysPopup from "../../../lib/popups/ApiKeysPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { mockFetchRoutes } from "../../helpers/fetch";
import { answerConfirmation } from "../../helpers/notifications";
import { renderWithQueryClient } from "../../helpers/render";

const HOMEPAGE = { id: 1, name: "Homepage", created_at: "2026-11-01T10:00:00Z" };

beforeEach(() => {
  queryClient.clear();
});

function renderCard() {
  const result = mockFetchRoutes({
    "/api/auth/api-keys": ({ init }: { init: RequestInit }) =>
      init.method === "POST"
        ? Response.json({
            id: 2,
            name: "Script",
            created_at: "2026-11-02T10:00:00Z",
            key: "s3cret",
          })
        : Response.json([HOMEPAGE]),
    "/api/auth/api-keys/1": { status: "deleted" },
  });
  renderWithQueryClient(ApiKeysPopup, {});
  return result;
}

it("shows a new key once and lists it by name", async () => {
  const { calls } = renderCard();
  await screen.findByText("Homepage");

  await fireEvent.input(screen.getByLabelText("New API key name"), { target: { value: "Script" } });
  await fireEvent.click(screen.getByRole("button", { name: "Create" }));

  expect(await screen.findByDisplayValue("s3cret")).toHaveAttribute("readonly");
  const list = screen.getByRole("list", { name: "API keys" });
  expect(within(list).getByText("Script")).toBeInTheDocument();
  expect(calls.find((call) => call.init.method === "POST")?.init.body).toBe(
    JSON.stringify({ name: "Script" }),
  );
  // The list came from the response, not a second request.
  expect(calls.filter((call) => !call.init.method || call.init.method === "GET")).toHaveLength(1);
});

it("revokes a key only once confirmed", async () => {
  const { calls } = renderCard();
  await fireEvent.click(await screen.findByRole("button", { name: "Revoke Homepage" }));
  await answerConfirmation(false);
  expect(calls.some((call) => call.init.method === "DELETE")).toBe(false);

  await fireEvent.click(screen.getByRole("button", { name: "Revoke Homepage" }));
  await answerConfirmation(true);

  await waitFor(() => expect(screen.queryByText("Homepage")).not.toBeInTheDocument());
  expect(calls.find((call) => call.init.method === "DELETE")?.url).toContain(
    "/api/auth/api-keys/1",
  );
});
