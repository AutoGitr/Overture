import { createMutation } from "@tanstack/svelte-query";
import {
  discardCatalogDraftMutation,
  saveCatalogDraftMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type {
  CatalogDraftUpdate,
  CatalogEntryDetail,
  TmdbSeasonPreview,
} from "../../generated/rest/types.gen";
import { storeCatalogDetail } from "../rest/cache";
import type { CatalogTarget } from "../router/routes";
import { createNotifier } from "../stores/notificationState.svelte";
import { errorMessage } from "./errors";

export type CatalogContext = {
  detail: CatalogEntryDetail;
  draft: CatalogDraft;
  seasons: TmdbSeasonPreview[];
};

/** Persist catalog choices without applying them to the media library. */
export class CatalogDraft {
  private readonly saveRequest = createMutation(() => saveCatalogDraftMutation());
  private readonly discardRequest = createMutation(() => discardCatalogDraftMutation());
  private readonly feedback = createNotifier();

  constructor(private readonly target: () => CatalogTarget | null) {}

  get busy() {
    return this.saveRequest.isPending || this.discardRequest.isPending;
  }

  async save(body: CatalogDraftUpdate): Promise<boolean> {
    const target = this.target();
    if (!target || this.busy) return false;
    this.feedback.clear();
    try {
      const detail = await this.saveRequest.mutateAsync({ path: target, body });
      storeCatalogDetail(target, detail);
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Draft could not be saved"));
      return false;
    }
  }

  async discard(): Promise<void> {
    const target = this.target();
    if (!target || this.busy) return;
    this.feedback.clear();
    try {
      const detail = await this.discardRequest.mutateAsync({ path: target });
      storeCatalogDetail(target, detail);
    } catch (error) {
      this.feedback.error(errorMessage(error, "Draft could not be discarded"));
    }
  }
}
