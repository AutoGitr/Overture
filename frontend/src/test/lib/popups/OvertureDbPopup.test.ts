import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import OvertureDbPopup from "../../../lib/popups/OvertureDbPopup.svelte";
import { storePublicDatasetStatus } from "../../../lib/realtime/cache";
import { publicDatasetSyncState } from "../../../lib/stores/jobStates.svelte";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import { publicDatasetStatus } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

const failure = (detail: string) => () => Response.json({ detail }, { status: 404 });

describe("OvertureDbPopup", () => {
  beforeEach(() => {
    publicDatasetSyncState.reset();
    uiState.closePopup();
  });

  it("renders the repository as a clickable link when configured", () => {
    storePublicDatasetStatus(publicDatasetStatus());

    renderWithQueryClient(OvertureDbPopup);

    const link = screen.getByRole("link", { name: "https://github.com/AutoGitr/OvertureDB" });
    expect(link).toHaveAttribute("href", "https://github.com/AutoGitr/OvertureDB");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders Not configured when repo_url is absent", () => {
    storePublicDatasetStatus(publicDatasetStatus({ enabled: false, repo_url: "" }));

    renderWithQueryClient(OvertureDbPopup);

    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Not configured")).toBeInTheDocument();
  });

  it("shows what the last sync imported", () => {
    storePublicDatasetStatus(
      publicDatasetStatus({
        last_stats: {
          entries: 130,
          items: 125,
          movies: 120,
          shows: 50,
          seasons: 75,
          errors: 0,
          catalog_url: null,
          catalog_bytes: 2048,
          catalog_uncompressed_bytes: 1024 * 1024,
          schema_version: 1,
        },
      }),
    );

    renderWithQueryClient(OvertureDbPopup);

    expect(screen.getByText("Movies").nextElementSibling).toHaveTextContent("120");
    expect(screen.getByText("Compressed").nextElementSibling).toHaveTextContent("2.0 KB");
    expect(screen.getByText("Unpacked").nextElementSibling).toHaveTextContent("1.00 MB");
    expect(screen.getByText("Schema").nextElementSibling).toHaveTextContent("1");
    expect(screen.queryByText("No synced file statistics yet.")).toBeNull();
  });

  it("links a bulk contribution issue to the repository", () => {
    storePublicDatasetStatus(publicDatasetStatus({ repo_url: "https://github.com/o/r/" }));

    renderWithQueryClient(OvertureDbPopup);

    expect(screen.getByRole("link", { name: "Create issue" })).toHaveAttribute(
      "href",
      "https://github.com/o/r/issues/new?template=bulk.yml",
    );
  });
});

describe("OvertureDbPopup settings", () => {
  beforeEach(() => {
    publicDatasetSyncState.reset();
  });

  it("saves the switch and confirms the server's answer", async () => {
    storePublicDatasetStatus(publicDatasetStatus({ enabled: false }));
    const { calls } = mockFetchRoutes({
      "/api/public-dataset/enabled": publicDatasetStatus({ enabled: true }),
    });
    renderWithQueryClient(OvertureDbPopup);
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();

    await fireEvent.click(screen.getByRole("checkbox", { name: "Enable OvertureDB" }));
    await fireEvent.click(save);

    expect(await screen.findByText("OvertureDB enabled.")).toBeInTheDocument();
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual({ enabled: true });
    expect(screen.getByRole("button", { name: "Sync OvertureDB Now" })).toBeEnabled();
    expect(save).toBeDisabled();
  });

  it("restores the switch when saving fails", async () => {
    storePublicDatasetStatus(publicDatasetStatus({ enabled: true }));
    mockFetchRoutes({ "/api/public-dataset/enabled": failure("Settings are read-only") });
    renderWithQueryClient(OvertureDbPopup);
    const toggle = screen.getByRole("checkbox", { name: "Enable OvertureDB" });

    await fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Sync OvertureDB Now" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Settings are read-only")).toBeInTheDocument();
    expect(toggle).toBeChecked();
  });

  it("starts a sync and shows it running from the click", async () => {
    storePublicDatasetStatus(publicDatasetStatus({ enabled: true }));
    mockFetchRoutes({ "/api/public-dataset/sync": { status: "started" } });
    renderWithQueryClient(OvertureDbPopup);

    await fireEvent.click(screen.getByRole("button", { name: "Sync OvertureDB Now" }));

    expect(await screen.findByRole("button", { name: "Syncing..." })).toBeDisabled();
    expect(publicDatasetSyncState.running).toBe(true);
  });

  it("explains a sync refused because OvertureDB is disabled on the server", async () => {
    storePublicDatasetStatus(publicDatasetStatus({ enabled: true }));
    mockFetchRoutes({ "/api/public-dataset/sync": { status: "disabled" } });
    renderWithQueryClient(OvertureDbPopup);

    await fireEvent.click(screen.getByRole("button", { name: "Sync OvertureDB Now" }));

    expect(
      await screen.findByText("Enable and save OvertureDB before syncing."),
    ).toBeInTheDocument();
    expect(publicDatasetSyncState.running).toBe(false);
  });

  it("reports a failed sync request", async () => {
    storePublicDatasetStatus(publicDatasetStatus({ enabled: true }));
    mockFetchRoutes({ "/api/public-dataset/sync": failure("Catalog unreachable") });
    renderWithQueryClient(OvertureDbPopup);

    await fireEvent.click(screen.getByRole("button", { name: "Sync OvertureDB Now" }));

    expect(await screen.findByText("Catalog unreachable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync OvertureDB Now" })).toBeEnabled();
  });
});

describe("OvertureDbPopup export", () => {
  beforeEach(() => {
    storePublicDatasetStatus(publicDatasetStatus());
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:selections"),
    });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  });

  afterEach(() => {
    delete (URL as Partial<typeof URL>).createObjectURL;
    delete (URL as Partial<typeof URL>).revokeObjectURL;
  });

  it("downloads the saved selections as a ZIP", async () => {
    mockFetchRoutes({
      "/api/public-dataset/export": () =>
        new Response("zip", { headers: { "Content-Type": "application/zip" } }),
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderWithQueryClient(OvertureDbPopup);

    await fireEvent.click(screen.getByRole("button", { name: "Export selections" }));

    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    const link = click.mock.contexts[0] as HTMLAnchorElement;
    expect(link.download).toBe("overturedb-selections.zip");
    expect(link.href).toBe("blob:selections");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:selections");
    const [[archive]] = vi.mocked(URL.createObjectURL).mock.calls as [[Blob]];
    expect(await archive.text()).toBe("zip");
  });

  it("reports a failed export", async () => {
    mockFetchRoutes({ "/api/public-dataset/export": failure("Nothing to export") });
    renderWithQueryClient(OvertureDbPopup);

    await fireEvent.click(screen.getByRole("button", { name: "Export selections" }));

    expect(await screen.findByText("Nothing to export")).toBeInTheDocument();
  });
});
