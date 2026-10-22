<script lang="ts">
  import type { ArtCandidate, ArtType } from "../../generated/rest/types.gen";
  import { candidateImageUrl } from "../utils/artDisplay";
  import ArtCard from "./ArtCard.svelte";

  /** One source's artwork candidates as a grid; images load as they scroll into view. */
  let {
    title,
    arts,
    artType,
    disabled,
    onselect,
    matched = false,
    showSource = false,
  }: {
    title: string;
    arts: ArtCandidate[];
    artType: ArtType;
    disabled: boolean;
    onselect: (art: ArtCandidate, previewUrl: string) => void;
    /** The candidates are matches for the local file. */
    matched?: boolean;
    /** Name each candidate's own source, for a section that mixes them. */
    showSource?: boolean;
  } = $props();
</script>

<div class="source-section">
  <div class="source-header">
    <h3 class="source-title">{title}</h3>
    <span class={["badge", { "badge-success": matched, "badge-muted": !matched }]}>
      {arts.length}
    </span>
  </div>

  <div class="art-grid aspect-{artType}">
    {#each arts as art (art.url)}
      <ArtCard
        {art}
        {disabled}
        onSelect={(art) => onselect(art, candidateImageUrl(art))}
        {showSource}
      />
    {/each}
  </div>
</div>

<style>
  .source-section {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .source-header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .source-title {
    font-size: var(--text-xs);
    font-weight: 600;
    letter-spacing: 0.08em;
    color: var(--text-tertiary);
    text-transform: uppercase;
  }

  .art-grid {
    display: grid;
    gap: var(--space-3);
    align-items: start;
  }

  /* Fixed-width poster columns, so candidates match the header poster exactly. */
  .art-grid.aspect-poster,
  .art-grid.aspect-season_poster {
    --art-aspect: 2 / 3;

    grid-template-columns: repeat(auto-fill, var(--art-poster-width));
  }

  .art-grid.aspect-background {
    --art-aspect: 16 / 9;

    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  }

  /* Same breakpoint as the detail-header poster, which matches one column. */
  @container detail-panel (max-width: 480px) {
    .art-grid.aspect-poster,
    .art-grid.aspect-season_poster {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .art-grid.aspect-background {
      grid-template-columns: 1fr;
    }
  }
</style>
