<script lang="ts">
  import type { ArtType } from "../../generated/rest/types.gen";
  import {
    ART_SOURCE_LABELS,
    ITEM_ART_TYPES,
    MATCH_THRESHOLD_MAX,
    PERFECT_MATCH_ONLY,
    SEASON_ART_TYPES,
  } from "../../generated/settings";
  import { ASSET_LABELS, SEASON_ONLY } from "../utils/artTypes";
  import type { AssetsForm } from "../utils/assetsForm.svelte";
  import SourceOrderList from "./SourceOrderList.svelte";
  import WorkflowCard from "./WorkflowCard.svelte";
  import WorkflowSection from "./WorkflowSection.svelte";

  let { form }: { form: AssetsForm } = $props();

  let config = $derived(form.config);
  let hasSelectedLibraries = $derived(form.hasSelectedLibraries);
  let seasonTypesEnabled = $derived(form.hasShowLibraries && hasSelectedLibraries);
</script>

{#snippet typeOption(artType: ArtType, enabled: boolean, reason?: string)}
  <label class="checkbox-group" title={enabled ? undefined : reason}>
    <input
      type="checkbox"
      checked={enabled && config.artTypes.includes(artType)}
      disabled={!enabled}
      onchange={() => form.toggleArtType(artType)}
    />
    <span>{ASSET_LABELS[artType]}</span>
  </label>
{/snippet}

<WorkflowCard title="Art" kind="art" bind:enabled={config.enableArt}>
  <WorkflowSection label="Types">
    <div class="filter-options">
      {#each ITEM_ART_TYPES as artType (artType)}
        {@render typeOption(artType, hasSelectedLibraries)}
      {/each}
      <!-- Collections have no seasons, so only a show library offers season art. -->
      {#if !form.collectionScope || form.hasShowLibraries}
        {#each SEASON_ART_TYPES as artType (artType)}
          {@render typeOption(artType, seasonTypesEnabled, SEASON_ONLY)}
        {/each}
      {/if}
    </div>
  </WorkflowSection>

  <WorkflowSection label="Sources" note="First match wins, top to bottom.">
    <SourceOrderList
      sourceOrder={config.artSourceOrder}
      selectedSources={config.selectedArtSources}
      labels={ART_SOURCE_LABELS}
      disabledSources={form.disabledSources}
      storageKey="art"
      ontoggle={(source) => form.toggleArtSource(source)}
      onmove={(source, target) => form.moveArtSource(source, target)}
    />
  </WorkflowSection>

  <WorkflowSection label="Local art matching">
    <div class="form-row">
      <span class="form-label">Distance threshold:</span>
      <input
        type="range"
        min={PERFECT_MATCH_ONLY}
        max={MATCH_THRESHOLD_MAX}
        bind:value={config.threshold}
        disabled={!form.localArtMatchingEnabled}
        class="flex-1"
      />
      {#if config.threshold === PERFECT_MATCH_ONLY}
        <span class="badge badge-success">Perfect match</span>
      {:else}
        <span
          class={[
            "badge",
            {
              "badge-success": config.threshold <= 3,
              "badge-warning": config.threshold > 3 && config.threshold <= 7,
              "badge-danger": config.threshold > 7,
            },
          ]}
        >
          {config.threshold} -
          {config.threshold <= 3 ? "strict" : config.threshold <= 7 ? "normal" : "loose"}
        </span>
      {/if}
    </div>
  </WorkflowSection>
</WorkflowCard>
