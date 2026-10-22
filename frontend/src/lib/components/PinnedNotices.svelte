<script lang="ts">
  import { onMount, type Snippet } from "svelte";
  import { notificationState } from "../stores/notificationState.svelte";

  /**
   * Shows ongoing conditions (offline, lost connection, failed loads) in the
   * notification stack for as long as this component is mounted. The content
   * keeps this component's reactivity wherever the stack renders it.
   */
  let { children }: { children: Snippet } = $props();

  onMount(() => notificationState.pin(children));
</script>
