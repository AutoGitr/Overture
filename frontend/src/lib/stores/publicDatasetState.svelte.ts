import { getPublicDatasetStatusOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
import type { PublicDatasetStatus } from "../../generated/rest/types.gen";
import { fetchPublicDatasetStatus } from "../rest/queries";
import { followQuery } from "../rest/queryClient";
import { errorMessage } from "../utils/errors";

/** The OvertureDB status the query cache holds, for views outside a query. */
class PublicDatasetState {
  status = $state<PublicDatasetStatus | null>(null);
  loading = $state(false);
  error = $state("");

  constructor() {
    followQuery<PublicDatasetStatus>(
      getPublicDatasetStatusOptions().queryKey,
      (status) => {
        this.status = status;
        this.error = "";
      },
      (error) => {
        this.error = errorMessage(error, "Failed to load OvertureDB status");
      },
    );
  }

  get loaded(): boolean {
    return this.status !== null;
  }

  get enabled(): boolean {
    return !!this.status?.enabled;
  }

  reset(): void {
    this.status = null;
    this.loading = false;
    this.error = "";
  }

  /** Read the status again; the cache delivers it, or its error. */
  async refresh(): Promise<void> {
    if (this.loading) return;
    this.loading = true;
    try {
      await fetchPublicDatasetStatus();
    } catch {
      // The failed fetch reaches `error` through the cache.
    } finally {
      this.loading = false;
    }
  }
}

export const publicDatasetState = new PublicDatasetState();
