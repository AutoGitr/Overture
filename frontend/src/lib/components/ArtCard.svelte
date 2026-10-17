<script lang="ts">
  import type { ArtCandidate } from "../../generated/rest/types.gen";
  import { candidateImageUrl } from "../utils/artDisplay";

  /**
   * ArtCard - displays a single art image option with metadata badges.
   * Props: art (object), onSelect (fn)
   */
  let {
    art,
    disabled = false,
    showSource = true,
    onSelect = () => {},
  }: {
    art: ArtCandidate;
    disabled?: boolean;
    showSource?: boolean;
    onSelect?: (art: ArtCandidate) => void;
  } = $props();

  function formatResolution(w: number | null | undefined, h: number | null | undefined) {
    if (!w || !h) return null;
    return `${w}x${h}`;
  }

  let sourceLabel = $derived(showSource ? art.source : null);
  let resolution = $derived(formatResolution(art.width, art.height));
  let infoBadge = $derived([sourceLabel, resolution].filter(Boolean).join(" | "));
</script>

<button {disabled} class="art-card card card-interactive" onclick={() => onSelect(art)}>
  <div
    class="art-card-image"
    style:aspect-ratio={art.width && art.height ? `${art.width} / ${art.height}` : null}
  >
    <img src={candidateImageUrl(art)} alt="" loading="lazy" decoding="async" />

    <div class="card-overlays">
      {#if infoBadge}
        <span class="badge badge-muted info-badge">{infoBadge}</span>
      {/if}

      {#if art.perfect_match}
        <span class="badge badge-success">Perfect Match</span>
      {:else if art.hamming !== undefined && art.hamming !== null}
        <span
          class="badge"
          class:badge-success={art.hamming <= 3}
          class:badge-warning={art.hamming > 3 && art.hamming <= 8}
          class:badge-danger={art.hamming > 8}
        >
          d={art.hamming}
        </span>
      {/if}
    </div>
  </div>
</button>

<style>
  .art-card {
    overflow: hidden;
    padding: 0;
    text-align: left;
    width: 100%;
    height: fit-content;
    box-shadow: none !important;
    border: none !important;
  }

  .art-card:disabled {
    cursor: wait;
    opacity: 0.65;
  }

  /* Sized before the image loads: by its own dimensions when known, else by
     the slot's shape (--art-aspect, set by the grid). */
  .art-card-image {
    position: relative;
    overflow: hidden;
    background: var(--bg-tertiary);
    aspect-ratio: var(--art-aspect, auto);
    min-height: 80px;
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .art-card-image img {
    width: 100%;
    height: 100%;
    object-fit: contain;
    display: block;
  }

  .art-card:hover .art-card-image img {
    cursor: pointer;
  }

  .art-card:hover .card-overlays {
    opacity: 0 !important;
  }

  .card-overlays {
    position: absolute;
    bottom: var(--space-1);
    left: var(--space-1);
    right: var(--space-1);
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    pointer-events: none;
  }

  .card-overlays :global(.badge) {
    background: var(--image-scrim) !important;
    color: oklch(100% 0 0) !important;
    border: none !important;
    box-shadow: none !important;
    white-space: nowrap !important;
    padding: 2px 6px !important;
    font-weight: 600;
  }

  .card-overlays :global(.info-badge) {
    display: block;
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .card-overlays :global(.badge-success) {
    color: var(--success) !important;
  }

  .card-overlays :global(.badge-warning) {
    color: var(--warning) !important;
  }

  .card-overlays :global(.badge-danger) {
    color: var(--danger) !important;
  }
</style>
