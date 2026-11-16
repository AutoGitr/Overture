import { createQuery } from "@tanstack/svelte-query";
import { listSavedFiltersOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
import type { MediaItemRead, MediaType } from "../../generated/rest/types.gen";
import { libraryFilterMatchOptions } from "../rest/queries";
import { criteriaPredicate, isEmptyCriteria, serverConditions } from "./libraryCriteria";

/** The saved custom filter a list applies, by media type. */
export interface CustomFilterTarget {
  mediaType: MediaType;
  filterId: number | null;
}

/**
 * The titles a saved custom filter keeps: its metadata and source conditions
 * as the server matched them, its status conditions against the live list.
 */
export class CustomFilterMatch {
  readonly #target;
  readonly #saved;
  readonly #match;
  readonly #criteria = $derived.by(() => {
    const target = this.#target();
    const saved = this.#saved.data?.find((entry) => entry.id === target?.filterId);
    return saved && !isEmptyCriteria(saved.criteria) ? saved.criteria : null;
  });
  readonly #conditions = $derived(this.#criteria ? serverConditions(this.#criteria) : []);

  /**
   * Whether a title passes; null without a filter, and none pass until the
   * server has answered.
   */
  readonly predicate: ((item: MediaItemRead) => boolean) | null = $derived.by(() => {
    const criteria = this.#criteria;
    if (!criteria) return null;
    if (this.#conditions.length === 0) return criteriaPredicate(criteria, []);
    const matched = this.#match.data?.item_ids;
    return matched ? criteriaPredicate(criteria, matched) : () => false;
  });

  constructor(target: () => CustomFilterTarget | null) {
    this.#target = target;
    this.#saved = createQuery(() => {
      const current = this.#target();
      return {
        ...listSavedFiltersOptions({ query: { media_type: current?.mediaType ?? "movie" } }),
        enabled: current?.filterId != null,
      };
    });
    this.#match = createQuery(() => ({
      ...libraryFilterMatchOptions({
        media_type: this.#target()?.mediaType ?? "movie",
        conditions: this.#conditions,
      }),
      enabled: this.#conditions.length > 0,
    }));
  }
}
