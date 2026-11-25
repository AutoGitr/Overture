import { createMutation, createQuery } from "@tanstack/svelte-query";
import {
  getCollectionDefaultsOptions,
  getCollectionGroupPolicyOptions,
  getCollectionGroupPolicyQueryKey,
  saveCollectionGroupPolicyMutation,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type {
  CollectionDimensionRead,
  CollectionGroupPolicyOutput,
  LibrarySectionRead,
  MediaType,
} from "../../generated/rest/types.gen";
import { queryClient } from "../rest/queryClient";
import { createNotifier } from "../stores/notificationState.svelte";
import { availableOrders } from "./collectionCriteria";
import { withDimension, type SetGenerator, type SetPolicy } from "./collectionFormShared.svelte";
import { draftOf } from "./draft.svelte";
import { errorMessage } from "./errors";
import { CollectionOptions as Capabilities } from "./libraries.svelte";
import { toggleSelectedValue } from "./popupSelection";

/** A group's defaults, and the set it runs when it is one. */
export type GroupDraft = SetPolicy & { generator: SetGenerator | null };

/**
 * What a group page edits and a new set saves: the group's defaults, which
 * its collections inherit, and for a set what it creates them from.
 */
export class CollectionGroupForm {
  /** The global defaults a group's choice left at Default falls back to. */
  readonly defaults = createQuery(() => getCollectionDefaultsOptions());
  readonly options: Capabilities;
  private readonly request = createMutation(() => saveCollectionGroupPolicyMutation());
  private readonly feedback = createNotifier();
  readonly #draft;

  constructor(
    private readonly libraries: () => LibrarySectionRead[],
    /** The media types a group's collections hold; a set's come from its libraries. */
    private readonly heldTypes: () => MediaType[],
    /** The saved group, taken once it loads; a new set starts empty. */
    saved: () => CollectionGroupPolicyOutput | null | undefined = () => null,
  ) {
    this.#draft = draftOf<GroupDraft>(saved, { generator: null });
    this.options = new Capabilities(() =>
      this.libraryIds.map((id) => ({ id, media_type: this.typeOf(id) })),
    );
  }

  get current(): GroupDraft {
    return this.#draft.current;
  }
  /** Start over from *draft*, as a preset fills the form. */
  reset(draft: GroupDraft) {
    this.#draft.current = draft;
  }
  get generator(): SetGenerator | null {
    return this.current.generator;
  }
  set generator(generator: SetGenerator | null) {
    this.current.generator = generator;
  }
  get busy() {
    return this.request.isPending;
  }
  /** The libraries the set spans; a group without one spans none. */
  get libraryIds(): string[] {
    return this.generator?.library_ids ?? [];
  }
  private typeOf(id: string): MediaType {
    return this.libraries().find((library) => library.id === id)?.media_type ?? "movie";
  }
  /** What the set's libraries hold, or the group's collections; an empty group either. */
  get mediaTypes(): MediaType[] {
    const held = this.generator ? this.libraryIds.map((id) => this.typeOf(id)) : this.heldTypes();
    const types = (["movie", "show"] as const).filter((type) => held.includes(type));
    return types.length ? types : ["movie", "show"];
  }
  /** What every library it covers can do. */
  get capabilities() {
    return this.options.shared(this.mediaTypes);
  }
  get dimensions(): CollectionDimensionRead[] {
    return this.capabilities?.dimensions ?? [];
  }
  get orders() {
    return availableOrders(this.capabilities, !!this.generator?.smart);
  }
  /** What takes requests and tags for the media it covers. */
  get arr() {
    if (!this.capabilities?.arr) return null;
    return this.mediaTypes.map((type) => (type === "movie" ? "Radarr" : "Sonarr")).join(" and ");
  }

  setLibrary(id: string, chosen: boolean) {
    const generator = this.generator;
    if (!generator || generator.library_ids.includes(id) === chosen) return;
    generator.library_ids = toggleSelectedValue(generator.library_ids, id);
  }

  /** Split the set by *dimension*, starting it and its collections with the dimension's defaults. */
  chooseDimension(dimension: CollectionDimensionRead) {
    const generator = this.generator;
    if (!generator) return;
    const previous = this.dimensions.find((entry) => entry.dimension === generator.dimension);
    this.generator = withDimension(generator, dimension, previous);
    this.current.order_type = dimension.order_type;
  }

  /**
   * Save the group as *name*, saying why it could not be.
   *
   * A *newSet* never replaces another set, and keeps the defaults an existing
   * group of that name already has wherever the form leaves one at Default.
   */
  async save(name: string, newSet = false): Promise<boolean> {
    if (this.busy) return false;
    const path = { name };
    try {
      let body = $state.snapshot(this.current);
      if (newSet) {
        const existing = await queryClient.fetchQuery(getCollectionGroupPolicyOptions({ path }));
        const chosen = Object.fromEntries(
          Object.entries(body).filter(([, value]) => value !== null && value !== undefined),
        );
        body = { ...existing, ...chosen, generator: body.generator };
      }
      const saved = await this.request.mutateAsync({ path, query: { new_set: newSet }, body });
      queryClient.setQueryData(getCollectionGroupPolicyQueryKey({ path }), saved);
      return true;
    } catch (error) {
      this.feedback.error(errorMessage(error, `Could not save "${name}"`));
      return false;
    }
  }
}
