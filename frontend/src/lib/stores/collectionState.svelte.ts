import type { CollectionRead } from "../../generated/rest/types.gen";

class CollectionState {
  selectedCollection = $state<CollectionRead | null>(null);

  selectCollection(collection: CollectionRead | null) {
    this.selectedCollection = collection;
  }

  patchSelectedCollection(serverId: string, update: Partial<CollectionRead>) {
    if (this.selectedCollection?.id === serverId) {
      this.selectedCollection = { ...this.selectedCollection, ...update };
    }
  }
}

export const collectionState = new CollectionState();
