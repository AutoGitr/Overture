import { createQuery } from "@tanstack/svelte-query";
import { getCatalogStatusOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
import { settingsState } from "../stores/settingsState.svelte";

/** Whether OvertureDB is on and may be browsed; create it while a component initialises. */
export class CatalogBrowsing {
  #status = createQuery(() => getCatalogStatusOptions());

  /** The catalog status has loaded, so `browsable` is final rather than assumed. */
  get loaded() {
    return this.#status.isSuccess;
  }

  /** The status has answered or failed; a failure leaves the catalog unbrowsable. */
  get settled() {
    return !this.#status.isPending;
  }

  get enabled() {
    return this.#status.data?.enabled ?? false;
  }

  /** The catalog's pages, sidebar and links to it are offered. */
  get browsable() {
    return this.enabled && settingsState.current.overturedb_browse;
  }
}
