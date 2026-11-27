import { createMutation, createQuery } from "@tanstack/svelte-query";
import {
  listPresetUsesOptions,
  listPresetUsesQueryKey,
  recordPresetUseMutation,
  reviewPresetUseMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type { PresetUseCreate, PresetUseRead } from "../../generated/rest/types.gen";
import { queryClient } from "../rest/queryClient";
import { createNotifier } from "../stores/notificationState.svelte";
import { errorMessage } from "./errors";

/** A collection, or the group a set was saved into. */
export type PresetSubject = { collection_id: number } | { group: string };

function sameSubject(use: PresetUseRead, subject: PresetSubject) {
  return "group" in subject
    ? use.group === subject.group
    : use.collection_id === subject.collection_id;
}

/**
 * The OvertureDB preset items collections and sets were saved from, what
 * OvertureDB has changed in each since, and taking or keeping those changes.
 */
export class PresetUses {
  readonly list;
  private readonly recordRequest = createMutation(() => recordPresetUseMutation());
  private readonly reviewRequest = createMutation(() => reviewPresetUseMutation());
  private readonly feedback = createNotifier();

  /** With *listed*, it reads every use; a form that only records one does not. */
  constructor(listed = true) {
    this.list = createQuery(() => ({ ...listPresetUsesOptions(), enabled: listed }));
  }

  /** The preset item *subject* was saved from, if any. */
  of(subject: PresetSubject): PresetUseRead | null {
    return this.list.data?.uses.find((use) => sameSubject(use, subject)) ?? null;
  }
  get busy() {
    return this.reviewRequest.isPending;
  }

  /** Keep track of the item a collection or set was just saved from; failing leaves it saved. */
  async record(body: PresetUseCreate) {
    try {
      await this.recordRequest.mutateAsync({ body });
      await queryClient.invalidateQueries({ queryKey: listPresetUsesQueryKey() });
    } catch (error) {
      this.feedback.error(
        errorMessage(error, "Saved, but OvertureDB's changes to its preset are not tracked"),
      );
    }
  }

  /** Take OvertureDB's changes to *subject*'s item, or keep it as it is. */
  async review(subject: PresetSubject, take: boolean): Promise<boolean> {
    try {
      await this.reviewRequest.mutateAsync({ body: { ...subject, take } });
      await queryClient.invalidateQueries({ queryKey: listPresetUsesQueryKey() });
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not review the preset's changes"));
      return false;
    }
  }
}
