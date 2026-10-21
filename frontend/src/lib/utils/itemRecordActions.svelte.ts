import { createMutation } from "@tanstack/svelte-query";
import {
  clearAllArtMutation,
  clearArtMutation,
  clearThemeMutation,
  deleteItemMutation,
  setMonitoredMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type { MediaItemRead } from "../../generated/rest/types.gen";
import { upsertLibraryItem } from "../rest/cache";
import { goToLibrary, type ArtSubTab } from "../router/routes";
import { downloadState } from "../stores/downloadState.svelte";
import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
import { errorMessage } from "./errors";

const ARTWORK_KEPT = "Local artwork files are kept.";

/**
 * What the detail view can do to a stored item's record: forget selections,
 * monitor it or remove it. Changed items arrive over the live connection, so
 * only the server's own answers are written to the cache here. Create it
 * during component initialisation.
 */
export class ItemRecordActions {
  readonly #feedback = createNotifier();
  readonly #clearAllArt = createMutation(() => clearAllArtMutation());
  readonly #clearArt = createMutation(() => clearArtMutation());
  readonly #clearTheme = createMutation(() => clearThemeMutation());
  readonly #setMonitored = createMutation(() => setMonitoredMutation());
  readonly #delete = createMutation(() => deleteItemMutation());

  constructor(private readonly item: () => MediaItemRead | null) {}

  get clearingArt(): boolean {
    return this.#clearArt.isPending || this.#clearAllArt.isPending;
  }

  get themeBusy(): boolean {
    const item = this.item();
    return (
      this.#clearTheme.isPending ||
      (!!item &&
        downloadState
          .getJobsForItem(item.id)
          .some((job) => job.job_type === "theme" && job.status === "running"))
    );
  }

  get monitoring(): boolean {
    return this.#setMonitored.isPending;
  }

  get deleting(): boolean {
    return this.#delete.isPending;
  }

  /** Forget one art tab's saved selection; the seasons tab forgets every season's. */
  async clearArt(tab: ArtSubTab): Promise<void> {
    const item = this.item();
    if (!item || this.clearingArt) return;
    if (!(await this.#confirm(`Forget the saved ${tab} selection?`, ARTWORK_KEPT))) {
      return;
    }
    await this.#run("Clear art failed", () =>
      this.#clearArt.mutateAsync({
        path: { item_id: item.id, art_type: tab === "seasons" ? "season_poster" : tab },
      }),
    );
  }

  async clearAllArt(): Promise<void> {
    const item = this.item();
    if (!item || this.clearingArt) return;
    if (
      !(await this.#confirm("Forget every saved artwork selection?", ARTWORK_KEPT, "Forget all"))
    ) {
      return;
    }
    await this.#run("Clear all art failed", () =>
      this.#clearAllArt.mutateAsync({ path: { item_id: item.id } }),
    );
  }

  async clearTheme(): Promise<void> {
    const item = this.item();
    if (!item || this.themeBusy) return;
    if (
      !(await this.#confirm("Forget the saved theme selection?", "The local theme file is kept."))
    ) {
      return;
    }
    await this.#run("Clear theme failed", () =>
      this.#clearTheme.mutateAsync({ path: { item_id: item.id } }),
    );
  }

  async toggleMonitored(): Promise<void> {
    const item = this.item();
    if (!item) return;
    await this.#run("Toggle monitored failed", async () => {
      const { monitored } = await this.#setMonitored.mutateAsync({
        path: { item_id: item.id },
        body: { monitored: !item.monitored },
      });
      upsertLibraryItem({ ...item, monitored });
    });
  }

  async delete(): Promise<void> {
    const item = this.item();
    if (!item) return;
    const confirmed = await confirmAction({
      title: `Remove ${item.title ?? "this item"} from Overture?`,
      message:
        "Its saved record will be removed. Local files and the media server item are kept, so it may return after a sync.",
      confirmLabel: "Remove",
      destructive: true,
    });
    if (!confirmed) return;
    await this.#run("Delete item failed", async () => {
      await this.#delete.mutateAsync({ path: { item_id: item.id } });
      goToLibrary(item.media_type);
    });
  }

  #confirm(title: string, message: string, confirmLabel = "Forget"): Promise<boolean> {
    return confirmAction({ title, message, confirmLabel, destructive: true });
  }

  async #run(failure: string, action: () => Promise<unknown>): Promise<void> {
    this.#feedback.clear();
    try {
      await action();
    } catch (err) {
      this.#feedback.error(errorMessage(err, failure));
    }
  }
}
