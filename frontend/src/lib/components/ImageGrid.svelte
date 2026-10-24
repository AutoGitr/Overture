<script lang="ts">
  import type { Snippet } from "svelte";
  import type { ArtType } from "../../generated/rest/types.gen";

  let { artType = "poster", children }: { artType?: ArtType; children: Snippet } = $props();
</script>

<div class="image-grid aspect-{artType}">
  {@render children()}
</div>

<style>
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
