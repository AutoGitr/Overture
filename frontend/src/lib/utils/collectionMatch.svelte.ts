import { createMutation, createQuery } from "@tanstack/svelte-query";
import {
  resetCollectionMatchMutation,
  searchTmdbOptions,
  setCollectionMatchMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type { CollectionDetail } from "../../generated/rest/types.gen";
import { storeCollectionDetail } from "../rest/cache";
import { createNotifier } from "../stores/notificationState.svelte";
import { settingsState } from "../stores/settingsState.svelte";
import { errorMessage } from "./errors";

/** Search and override a collection's franchise without copying server state. */
export class CollectionMatcher {
  text = $state("");
  submitted = $state("");
  readonly search = createQuery(() => ({
    ...searchTmdbOptions({ query: { media_type: "movie", query: this.submitted } }),
    enabled: !!this.submitted && settingsState.current.tmdb_configured,
  }));
  private readonly setRequest = createMutation(() => setCollectionMatchMutation());
  private readonly resetRequest = createMutation(() => resetCollectionMatchMutation());
  private readonly feedback = createNotifier();

  constructor(private readonly current: () => CollectionDetail) {}

  get busy() {
    return this.setRequest.isPending || this.resetRequest.isPending;
  }

  get matches() {
    return this.search.data?.results.filter((result) => result.kind === "collection") ?? [];
  }

  submitSearch() {
    const query = this.text.trim();
    if (query === this.submitted) void this.search.refetch();
    else this.submitted = query;
  }

  async match(tmdbId: number | null) {
    if (this.busy) return;
    const collection = this.current();
    try {
      storeCollectionDetail(
        await this.setRequest.mutateAsync({
          path: { collection_id: collection.id },
          body: { media_type: collection.media_type, tmdb_collection_id: tmdbId },
        }),
      );
      this.submitted = "";
      this.text = "";
    } catch (error) {
      this.feedback.error(errorMessage(error, "Match could not be saved"));
    }
  }

  async reset() {
    if (this.busy) return;
    const collection = this.current();
    try {
      storeCollectionDetail(
        await this.resetRequest.mutateAsync({
          path: { collection_id: collection.id },
          query: { media_type: collection.media_type },
        }),
      );
    } catch (error) {
      this.feedback.error(errorMessage(error, "Match could not be reset"));
    }
  }
}
