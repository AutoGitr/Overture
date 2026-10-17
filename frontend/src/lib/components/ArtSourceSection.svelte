<script lang="ts">
  import type { ArtCandidate, ArtType } from "../../generated/rest/types.gen";
  import { settingsState } from "../stores/settingsState.svelte";
  import { candidateImageUrl } from "../utils/artDisplay";
  import ArtCard from "./ArtCard.svelte";

  /**
   * One source's artwork candidates as a grid. A paged section shows the
   * configured first results and grows on request; matches show at once.
   */
  let {
    title,
    arts,
    artType,
    disabled,
    onselect,
    paged = true,
    matched = false,
    showSource = false,
  }: {
    title: string;
    arts: ArtCandidate[];
    artType: ArtType;
    disabled: boolean;
    onselect: (art: ArtCandidate, previewUrl: string) => void;
    paged?: boolean;
    /** The candidates are matches for the local file. */
    matched?: boolean;
    /** Name each candidate's own source, for a section that mixes them. */
    showSource?: boolean;
  } = $props();

  /** How many are shown once the user asked for more; until then the setting decides. */
  let requested = $state<number | null>(null);
  let shown = $derived(paged ? (requested ?? settingsState.current.initial_results) : arts.length);
  let remaining = $derived(Math.max(0, arts.length - shown));
</script>

<div class="source-section">
  <div class="source-header">
    <h3 class="source-title">{title}</h3>
    <span class="badge" class:badge-success={matched} class:badge-muted={!matched}>
      {paged ? `${Math.min(shown, arts.length)} / ${arts.length}` : arts.length}
    </span>
  </div>

  <div class="art-grid aspect-{artType}">
    {#each arts.slice(0, shown) as art (art.url)}
      <ArtCard
        {art}
        {disabled}
        onSelect={(art) => onselect(art, candidateImageUrl(art))}
        {showSource}
      />
    {/each}
  </div>

  {#if remaining > 0}
    <div class="show-more-row">
      <button
        class="btn btn-secondary"
        onclick={() => (requested = shown + settingsState.current.load_more_step)}
      >
        Show more ({remaining} remaining)
      </button>
      <button class="btn btn-secondary" onclick={() => (requested = arts.length)}>Show all</button>
    </div>
  {/if}
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

  .show-more-row {
    display: flex;
    gap: var(--space-3);
    justify-content: flex-start;
    margin-top: var(--space-2);
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
