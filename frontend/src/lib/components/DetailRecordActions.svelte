<script lang="ts">
  import Database from "@lucide/svelte/icons/database";
  import Eye from "@lucide/svelte/icons/eye";
  import EyeOff from "@lucide/svelte/icons/eye-off";
  import Trash from "@lucide/svelte/icons/trash";
  import type { Snippet } from "svelte";
  import { uiState } from "../stores/uiState.svelte";

  let {
    monitored,
    monitoring,
    deleting,
    deleteLabel,
    deleteBlocker = null,
    ontoggle,
    ondelete,
    beforeDelete,
  }: {
    monitored: boolean;
    monitoring: boolean;
    deleting: boolean;
    deleteLabel: string;
    /** Why it cannot be deleted, shown on the disabled button. */
    deleteBlocker?: string | null;
    ontoggle: () => void;
    ondelete: () => void;
    /** Actions of this kind of record, shown just before Delete. */
    beforeDelete?: Snippet;
  } = $props();
</script>

<button
  type="button"
  class="tab-item"
  onclick={() => uiState.openPopupByName("database")}
  title="Open Database Record"
>
  <Database size={16} />
</button>
<button
  type="button"
  class={["tab-item", { danger: !monitored }]}
  onclick={() => {
    // The toggle settles too quickly for a disabled state to help, so a repeat click is ignored.
    if (!monitoring) ontoggle();
  }}
  title={monitored ? "Monitored - click to unmonitor" : "Unmonitored - click to monitor"}
  aria-pressed={monitored}
  aria-busy={monitoring}
>
  {#if monitored}<Eye size={16} />{:else}<EyeOff size={16} />{/if}
</button>
{@render beforeDelete?.()}
<button
  type="button"
  class="tab-item danger"
  onclick={ondelete}
  title={deleteBlocker ?? deleteLabel}
  aria-label={deleteLabel}
  disabled={deleting || !!deleteBlocker}
>
  <Trash size={16} />
</button>
