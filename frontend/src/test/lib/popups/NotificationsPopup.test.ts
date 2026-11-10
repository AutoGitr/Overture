import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, expect, it } from "vitest";
import type { NotificationSettingsRead } from "../../../generated/rest/types.gen";
import NotificationsPopup from "../../../lib/popups/NotificationsPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { notificationState } from "../../../lib/stores/notificationState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import { renderWithQueryClient } from "../../helpers/render";

const RULE = { failed: true, stopped: false, completed: "never", scheduled_only: false } as const;

function settings(service: "discord" | null): NotificationSettingsRead {
  return {
    service,
    service_label: service ? "Discord" : null,
    rules: [
      { ...RULE, kind: "sync", label: "Library sync" },
      { ...RULE, kind: "backup", label: "Backup" },
    ],
  };
}

beforeEach(() => {
  queryClient.clear();
});

it("saves each kind's rule and says so", async () => {
  const { calls } = mockFetchRoutes({
    "/api/notifications": settings("discord"),
  });
  renderWithQueryClient(NotificationsPopup, {});

  const sync = await screen.findByRole("region", { name: "Library sync" });
  await fireEvent.click(within(sync).getByLabelText("Stopped"));
  await fireEvent.change(within(sync).getByLabelText("Completed"), {
    target: { value: "changes" },
  });
  await fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(calls.some((call) => call.init.method === "PUT")).toBe(true));
  const body = JSON.parse(String(calls.find((call) => call.init.method === "PUT")?.init.body));
  expect(body.rules[0]).toEqual({
    kind: "sync",
    failed: true,
    stopped: true,
    completed: "changes",
    scheduled_only: false,
  });
  await waitFor(() =>
    expect(notificationState.toasts.map((item) => item.message)).toContain(
      "Notification settings saved.",
    ),
  );
});

it("sends a test only once NOTIFY_URL is set and reports the result", async () => {
  mockFetchRoutes({
    "/api/notifications": settings(null),
  });
  renderWithQueryClient(NotificationsPopup, {});
  expect(await screen.findByText(/Set/)).toHaveTextContent("NOTIFY_URL");
  expect(screen.getByRole("button", { name: "Send test notification" })).toBeDisabled();
});

it("reports a refused test notification", async () => {
  mockFetchRoutes({
    "/api/notifications": settings("discord"),
    "/api/notifications/test": () =>
      Response.json({ detail: "The service refused the notification: HTTP 403" }, { status: 502 }),
  });
  renderWithQueryClient(NotificationsPopup, {});
  await fireEvent.click(await screen.findByRole("button", { name: "Send test notification" }));
  await waitFor(() =>
    expect(notificationState.toasts.map((item) => item.message).join()).toContain("HTTP 403"),
  );
});
