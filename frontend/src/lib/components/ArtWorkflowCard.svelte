<script lang="ts">
  import { ITEM_ART_TYPES, SEASON_ART_TYPES } from "../../generated/settings";
  import { ASSET_LABELS } from "../utils/artTypes";
  import type { ArtType } from "../../generated/rest/types.gen";
  import { ART_SOURCE_LABELS } from "../../generated/settings";
  import {} from "../utils/assetsPopup";
  import { MATCH_THRESHOLD_MAX, PERFECT_MATCH_ONLY } from "../../generated/settings";
  import SourceOrderList from "./SourceOrderList.svelte";

  let {
    artTypes,
    hasSelectedLibraries,
    hasShowLibraries,
    artSourceOrder,
    selectedArtSources,
    disabledSources,
    threshold,
    localArtMatchingEnabled,
    ontoggletype,
    ontogglesource,
    onmovesource,
    onthresholdchange,
  }: {
    artTypes: ArtType[];
    hasSelectedLibraries: boolean;
    hasShowLibraries: boolean;
    artSourceOrder: string[];
    selectedArtSources: string[];
    disabledSources: readonly string[];
    threshold: number;
    localArtMatchingEnabled: boolean;
    ontoggletype: (type: ArtType) => void;
    ontogglesource: (source: string) => void;
    onmovesource: (source: string, target: string) => void;
    onthresholdchange: (value: number) => void;
  } = $props();
</script>

<div class="option-card workflow-card">
  <div class="workflow-header">
    <span class="form-label">Art</span>
  </div>

  <div class="asset-section">
    <span class="form-label">Types</span>
    <div class="art-type-group">
      <div class="filter-options">
        {#each ITEM_ART_TYPES as artType (artType)}
          <label class="checkbox-group">
            <input
              type="checkbox"
              checked={hasSelectedLibraries && artTypes.includes(artType)}
              disabled={!hasSelectedLibraries}
              onchange={() => ontoggletype(artType)}
            />
            <span>{ASSET_LABELS[artType]}</span>
          </label>
        {/each}
      </div>
    </div>
    <div
      class="art-type-group"
      class:art-type-group-disabled={!hasShowLibraries || !hasSelectedLibraries}
    >
      <div class="art-type-group-label">
        Shows only
        {#if !hasShowLibraries}
          <span class="show-warning">- no shows selected</span>
        {/if}
      </div>
      <div class="filter-options">
        {#each SEASON_ART_TYPES as artType (artType)}
          <label class="checkbox-group">
            <input
              type="checkbox"
              checked={hasShowLibraries && hasSelectedLibraries && artTypes.includes(artType)}
              disabled={!hasShowLibraries || !hasSelectedLibraries}
              onchange={() => ontoggletype(artType)}
            />
            <span>{ASSET_LABELS[artType]}</span>
          </label>
        {/each}
      </div>
    </div>
  </div>

  <div class="asset-section">
    <span class="form-label">Sources</span>
    <p class="option-note">
      Tried top to bottom; the first match wins. Local art matching picks the source image closest
      to your current one.
    </p>
    <SourceOrderList
      sourceOrder={artSourceOrder}
      selectedSources={selectedArtSources}
      labels={ART_SOURCE_LABELS}
      {disabledSources}
      storageKey="art"
      ontoggle={ontogglesource}
      onmove={onmovesource}
    />
  </div>

  <div class="asset-section">
    <span class="form-label">Matching</span>
    <p class="option-note">For local art matching only. Lower is stricter.</p>
    <div class="form-row">
      <span class="form-label">Distance threshold:</span>
      <input
        type="range"
        min={PERFECT_MATCH_ONLY}
        max={MATCH_THRESHOLD_MAX}
        value={threshold}
        disabled={!localArtMatchingEnabled}
        oninput={(event) =>
          onthresholdchange(Number((event.currentTarget as HTMLInputElement).value))}
        class="flex-1"
      />
      {#if threshold === PERFECT_MATCH_ONLY}
        <span class="badge badge-success">Perfect match</span>
      {:else}
        <span
          class="badge"
          class:badge-success={threshold <= 3}
          class:badge-warning={threshold > 3 && threshold <= 7}
          class:badge-danger={threshold > 7}
        >
          {threshold} - {threshold <= 3 ? "strict" : threshold <= 7 ? "normal" : "loose"}
        </span>
      {/if}
    </div>
  </div>
</div>
