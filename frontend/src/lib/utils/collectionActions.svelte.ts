import { createMutation } from "@tanstack/svelte-query";
import {
  removeAllCollectionArtMutation,
  removeCollectionArtMutation,
  removeCollectionThemeMutation,
  setCollectionThemeMutation,
  setCollectionMonitoredMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type { CollectionDetail } from "../../generated/rest/types.gen";
import { patchCollection } from "../rest/cache";
import { downloadStageLabel, downloadState } from "../stores/downloadState.svelte";
import { createNotifier } from "../stores/notificationState.svelte";
import { askRemoval, removedMessage } from "./assetRemoval";
import { errorMessage } from "./errors";
import { beginAutoAdvance, collectionKey } from "./autoAdvance";
import { handleRecordSelectionAdvance } from "./recordAdvance";

/** Collection asset actions shared by the header and the active section. */
export class CollectionActions {
  private readonly feedback = createNotifier();
  private readonly clearArtRequest = createMutation(() => removeCollectionArtMutation());
  private readonly clearAllArtRequest = createMutation(() => removeAllCollectionArtMutation());
  private readonly deleteThemeRequest = createMutation(() => removeCollectionThemeMutation());
  private readonly setThemeRequest = createMutation(() => setCollectionThemeMutation());
  private readonly setMonitoredRequest = createMutation(() => setCollectionMonitoredMutation());
  private chosen = $state<{ collectionId: number; videoId: string } | null>(null);

  constructor(private readonly current: () => CollectionDetail) {}

  private get themeJob() {
    return downloadState.getCollectionJob(this.current().id);
  }
  get activeThemeJob() {
    const job = this.themeJob;
    return job?.status === "running" ? job : null;
  }
  get themeBusy() {
    return (
      this.setThemeRequest.isPending || !!this.activeThemeJob || this.themeJob?.status === "pending"
    );
  }
  get uploading() {
    return this.themeBusy || this.deleteThemeRequest.isPending;
  }
  get uploadingVideoId() {
    return this.themeBusy && this.chosen?.collectionId === this.current().id
      ? this.chosen.videoId
      : null;
  }
  get uploadProgressLabel() {
    return this.activeThemeJob ? downloadStageLabel(this.activeThemeJob) : "";
  }
  get monitoring() {
    return this.setMonitoredRequest.isPending;
  }

  async toggleMonitored() {
    if (this.monitoring) return;
    const target = this.current();
    this.feedback.clear();
    try {
      const { monitored } = await this.setMonitoredRequest.mutateAsync({
        path: { collection_id: target.id },
        body: { monitored: !target.monitored },
      });
      patchCollection(target.id, { monitored });
    } catch (error) {
      this.feedback.error(errorMessage(error, "Toggle monitored failed"));
    }
  }

  async selectTheme(videoId: string): Promise<boolean> {
    if (this.uploading) return false;
    const target = this.current();
    this.chosen = { collectionId: target.id, videoId };
    this.feedback.clear();
    const advanceContext = beginAutoAdvance();
    try {
      const result = await this.setThemeRequest.mutateAsync({
        body: { youtube_id: videoId },
        path: { collection_id: target.id },
      });
      if (result.job_id)
        downloadState.trackQueuedCollectionJob({
          jobId: result.job_id,
          collectionId: target.id,
          title: target.title,
        });
      // An inactive collection keeps the choice; the sync that restores it downloads it.
      else patchCollection(target.id, { youtube_id: videoId, theme_status: result.theme_status });
      handleRecordSelectionAdvance(collectionKey(target.id), "theme", advanceContext);
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Upload failed"));
      return false;
    }
  }

  get clearingArt() {
    return this.clearArtRequest.isPending || this.clearAllArtRequest.isPending;
  }

  async clearArt(artType: "poster" | "background" | "all") {
    if (this.clearingArt) return;
    const collection = this.current();
    this.feedback.clear();
    const what = artType === "all" ? "its art" : `the ${artType}`;
    try {
      const removal = await askRemoval(
        { asset: artType === "all" ? "art" : artType, collection_ids: [collection.id] },
        what,
      );
      if (!removal) return;
      if (artType === "all")
        await this.clearAllArtRequest.mutateAsync({
          path: { collection_id: collection.id },
          query: removal,
        });
      else
        await this.clearArtRequest.mutateAsync({
          path: { collection_id: collection.id, art_type: artType },
          query: removal,
        });
      this.feedback.success(removedMessage(what, removal, artType === "all"));
    } catch (error) {
      this.feedback.error(errorMessage(error, "Remove artwork failed"));
    }
  }

  async clearTheme() {
    if (this.uploading) return;
    const target = this.current();
    this.feedback.clear();
    try {
      const removal = await askRemoval(
        { asset: "theme", collection_ids: [target.id] },
        "the collection theme",
      );
      if (!removal) return;
      const cleared = await this.deleteThemeRequest.mutateAsync({
        path: { collection_id: target.id },
        query: removal,
      });
      patchCollection(target.id, {
        has_theme: cleared.has_theme,
        ...(removal.forget
          ? { youtube_id: null, youtube_title: null, youtube_duration: null }
          : {}),
        theme_status: cleared.theme_status,
      });
      this.feedback.success(removedMessage("the collection theme", removal));
    } catch (error) {
      this.feedback.error(errorMessage(error, "Remove theme failed"));
    }
  }
}
