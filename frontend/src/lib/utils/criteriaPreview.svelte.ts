import { createMutation, createQuery, keepPreviousData } from "@tanstack/svelte-query";
import {
  previewCollectionMutation,
  recommendCollectionKindOptions,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import { ruleBody, type CollectionFormLike } from "./collectionFormShared.svelte";

/**
 * Shows what a form's criteria select before anything is saved, and
 * which collection kind suits them as they are edited.
 */
export class CriteriaPreview {
  private readonly request = createMutation(() => previewCollectionMutation());
  private readonly kind;

  constructor(
    private readonly form: () => CollectionFormLike,
    private readonly collectionId: () => number | null = () => null,
  ) {
    this.kind = createQuery(() => {
      const { libraries } = form().rule;
      return {
        ...recommendCollectionKindOptions({ body: { rule: ruleBody(form()) } }),
        enabled:
          !!form().capabilities.data?.smart &&
          libraries.length > 0 &&
          libraries.every(
            ({ criteria }) => criteria.conditions.length + criteria.groups.length > 0,
          ),
        // An unfinished condition is refused; the last advice stands until it is complete.
        placeholderData: keepPreviousData,
      };
    });
  }

  /** The kind the criteria suit, on servers with smart collections. */
  get recommendation() {
    return this.kind.data ?? null;
  }

  /** What one library's criteria selected when last previewed. */
  resultFor(libraryId: string) {
    return this.request.data?.libraries.find((entry) => entry.library_id === libraryId);
  }
  get pending() {
    return this.request.isPending;
  }
  get error() {
    return this.request.error;
  }

  run() {
    const form = this.form();
    this.request.mutate({
      body: {
        rule: { ...ruleBody(form), limit: form.rule.limit ?? null },
        // A saved collection never counts as another one holding a title.
        collection_id: this.collectionId(),
      },
    });
  }
}
