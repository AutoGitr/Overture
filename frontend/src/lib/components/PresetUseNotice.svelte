<script lang="ts">
  import { PresetUses, type PresetSubject } from "../utils/presetUses.svelte";
  import Notice from "./Notice.svelte";

  let {
    subject,
    onreviewed,
  }: {
    subject: PresetSubject;
    /** Load what taking OvertureDB's changes saved into the form. */
    onreviewed: () => Promise<void>;
  } = $props();

  const uses = new PresetUses();
  let use = $derived(uses.of(subject));
  let source = $derived(use ? `${use.preset_title ?? use.preset_id} preset: ${use.item}` : "");

  async function review(take: boolean) {
    if (await uses.review(subject, take)) await onreviewed();
  }
</script>

{#if use?.gone}
  <Notice
    tone="warning"
    title="OvertureDB no longer publishes it"
    message={`It came from the ${source}. What was saved stays as it is.`}
    action={{ label: "Stop tracking", run: () => void review(false), pending: uses.busy }}
  />
{:else if use?.changes.length}
  <Notice
    tone="info"
    title="OvertureDB changed its preset"
    message={`The ${source} has new ${use.changes.join(", ")}. Taking them changes only those; everything else stays as you have it.`}
    action={{ label: "Take changes", run: () => void review(true), pending: uses.busy }}
  >
    <button
      type="button"
      class="btn btn-ghost btn-sm"
      disabled={uses.busy}
      onclick={() => void review(false)}>Keep mine</button
    >
  </Notice>
{:else if use}
  <p class="hint">From OvertureDB's {source}; changes OvertureDB makes to it show here.</p>
{/if}
