<script lang="ts">
  import type { Snippet } from "svelte";
  import type { ArtType } from "../../generated/rest/types.gen";

  let {
    artType = "poster",
    title,
    count,
    matched = false,
    children,
  }: {
    artType?: ArtType;
    title?: string;
    count?: number;
    matched?: boolean;
    children: Snippet;
  } = $props();
</script>

<div class="grid-section">
  {#if title}
    <div class="heading">
      <h3>{title}</h3>
      {#if count !== undefined}<span class={["badge", matched ? "badge-success" : "badge-muted"]}
          >{count}</span
        >{/if}
    </div>
  {/if}
  <div class="image-grid aspect-{artType}">
    {@render children()}
  </div>
</div>

<style>
  .grid-section {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .heading {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  h3 {
    font-size: var(--text-xs);
    font-weight: 600;
    letter-spacing: 0.08em;
    color: var(--text-tertiary);
    text-transform: uppercase;
  }
  .image-grid {
    display: grid;
    gap: var(--space-3);
    align-items: start;
  }

  .aspect-poster,
  .aspect-season_poster {
    --art-aspect: 2 / 3;
    grid-template-columns: repeat(auto-fill, var(--art-poster-width));

    @container detail-panel (max-width: 480px) {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  .aspect-background {
    --art-aspect: 16 / 9;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));

    @container detail-panel (max-width: 480px) {
      grid-template-columns: 1fr;
    }
  }
</style>
