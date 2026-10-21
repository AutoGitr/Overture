<script lang="ts">
  import type { Snippet } from "svelte";
  import { isImageLoaded, markImageLoaded } from "../utils/imagePreload";

  let {
    src,
    fallbackSrc = null,
    alt = "",
    loading = "lazy",
    fetchpriority = "auto",
    loadDelayMs = 0,
    placeholder,
  }: {
    src: string | null;
    fallbackSrc?: string | null;
    alt?: string;
    loading?: "lazy" | "eager";
    fetchpriority?: "high" | "low" | "auto";
    /** Wait this long before loading a source not yet loaded, so fast scrolling skips it. */
    loadDelayMs?: number;
    /** Shown when there is no image to show, never while one is on its way. */
    placeholder: Snippet;
  } = $props();

  // Starts over whenever the sources change; a failed load adds to it.
  let failedSources = $derived.by((): string[] => {
    void [src, fallbackSrc];
    return [];
  });
  let delayElapsed = $state(false);
  let ready = $derived(loadDelayMs <= 0 || delayElapsed || (src !== null && isImageLoaded(src)));
  let candidate = $derived(
    [src, fallbackSrc].find((source) => source && !failedSources.includes(source)) ?? null,
  );
  let currentSrc = $derived(ready ? candidate : null);

  $effect(() => {
    if (delayElapsed || loadDelayMs <= 0) return;
    const timeout = setTimeout(() => (delayElapsed = true), loadDelayMs);
    return () => clearTimeout(timeout);
  });

  function handleLoad() {
    if (currentSrc) markImageLoaded(currentSrc);
  }

  function handleError() {
    if (currentSrc) failedSources = [...failedSources, currentSrc];
  }
</script>

{#if currentSrc}
  <img
    {alt}
    {loading}
    {fetchpriority}
    decoding="async"
    src={currentSrc}
    referrerpolicy="no-referrer"
    onload={handleLoad}
    onerror={handleError}
  />
{:else if !candidate}
  {@render placeholder()}
{/if}

<style>
  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
</style>
