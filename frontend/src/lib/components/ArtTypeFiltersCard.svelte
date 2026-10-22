<script lang="ts">
  import type { ArtType, ServerAsset } from "../../generated/rest/types.gen";
  import { ITEM_ART_TYPES, SEASON_ART_TYPES } from "../../generated/settings";
  import { ASSET_LABELS, SEASON_ONLY } from "../utils/artTypes";

  let {
    artTypes,
    hasSelectedFolders,
    hasShowFolders,
    themeChecked,
    ontoggletype,
    ontoggletheme,
  }: {
    artTypes: readonly ServerAsset[];
    hasSelectedFolders: boolean;
    hasShowFolders: boolean;
    themeChecked: boolean;
    ontoggletype: (type: ArtType) => void;
    ontoggletheme: (checked: boolean) => void;
  } = $props();
</script>

<div class={["option-card", { "option-card-disabled": !hasSelectedFolders }]}>
  <span class="form-label">Check for</span>
  {#snippet typeOption(artType: ArtType, enabled: boolean, reason?: string)}
    <label class="checkbox-group" title={enabled ? undefined : reason}>
      <input
        type="checkbox"
        checked={enabled && artTypes.includes(artType)}
        disabled={!enabled}
        onchange={() => ontoggletype(artType)}
      />
      <span>{ASSET_LABELS[artType]}</span>
    </label>
  {/snippet}
  <div class="filter-options">
    {#each ITEM_ART_TYPES as artType (artType)}
      {@render typeOption(artType, hasSelectedFolders)}
    {/each}
    {#each SEASON_ART_TYPES as artType (artType)}
      {@render typeOption(artType, hasSelectedFolders && hasShowFolders, SEASON_ONLY)}
    {/each}
  </div>
  <label class="checkbox-group">
    <input
      type="checkbox"
      checked={themeChecked}
      disabled={!hasSelectedFolders}
      onchange={(event) => ontoggletheme(event.currentTarget.checked)}
    />
    <span>Themes</span>
  </label>
</div>
