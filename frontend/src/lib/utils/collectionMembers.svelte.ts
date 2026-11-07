import { createQuery } from "@tanstack/svelte-query";
import { getCollectionOptions } from "../../generated/rest/@tanstack/svelte-query.gen";

/** The items a collection holds, for the filter that shows only them. */
export class CollectionMembers {
  readonly #query;
  // eslint-disable-next-line svelte/prefer-svelte-reactivity -- never mutated: $derived rebuilds it whole
  readonly ids = $derived(new Set(this.#data()?.member_ids ?? []));

  constructor(collectionId: () => number | null) {
    this.#query = createQuery(() => {
      const id = collectionId();
      return {
        ...getCollectionOptions({ path: { collection_id: id ?? 0 } }),
        enabled: id !== null,
      };
    });
  }

  #data() {
    return this.#query.data;
  }
}
