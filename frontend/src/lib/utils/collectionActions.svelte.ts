import { createMutation } from "@tanstack/svelte-query";
import {
  deleteCollectionThemeMutation,
  clearCollectionArtMutation,
  clearAllCollectionArtMutation,
  setCollectionThemeMutation,
  setCollectionMonitoredMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type { CollectionDetail } from "../../generated/rest/types.gen";
import { patchCollection } from "../rest/cache";
import { downloadStageLabel, downloadState } from "../stores/downloadState.svelte";
import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
import { errorMessage } from "./errors";

/** Collection asset actions shared by the header and the active section. */
export class CollectionActions {
  private readonly feedback = createNotifier();
  private readonly clearArtRequest = createMutation(() => clearCollectionArtMutation());
  private readonly clearAllArtRequest = createMutation(() => clearAllCollectionArtMutation());
  private readonly deleteThemeRequest = createMutation(() => deleteCollectionThemeMutation());
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
        query: { media_type: target.media_type },
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
    try {
      const result = await this.setThemeRequest.mutateAsync({
        body: { media_type: target.media_type, youtube_id: videoId },
        path: { collection_id: target.id },
      });
      downloadState.trackQueuedCollectionJob({
        jobId: result.job_id,
        collectionId: target.id,
        title: target.title,
      });
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
    if (
      !(await confirmAction({
        title: "Forget selected collection artwork?",
        message: "Artwork on the media server is kept.",
        confirmLabel: "Forget",
      }))
    )
      return;
    const collection = this.current();
    try {
      const result =
        artType === "all"
          ? await this.clearAllArtRequest.mutateAsync({
              path: { collection_id: collection.id },
              query: { media_type: collection.media_type },
            })
          : await this.clearArtRequest.mutateAsync({
              path: { collection_id: collection.id, art_type: artType },
              query: { media_type: collection.media_type },
            });
      patchCollection(collection.id, result);
    } catch (error) {
      this.feedback.error(errorMessage(error, "Clear artwork failed"));
    }
  }

  async clearTheme() {
    if (this.uploading) return;
    const target = this.current();
    if (
      !(await confirmAction({
        title: "Remove the collection theme?",
        message: `The theme is removed from ${target.title} on the media server.`,
        confirmLabel: "Remove",
        destructive: true,
      }))
    )
      return;
    this.feedback.clear();
    try {
      const cleared = await this.deleteThemeRequest.mutateAsync({
        path: { collection_id: target.id },
        query: { media_type: target.media_type },
      });
      patchCollection(target.id, {
        has_theme: cleared.has_theme,
        youtube_id: null,
        youtube_title: null,
        youtube_duration: null,
        theme_status: cleared.theme_status,
      });
    } catch (error) {
      this.feedback.error(errorMessage(error, "Clear failed"));
    }
  }
}
