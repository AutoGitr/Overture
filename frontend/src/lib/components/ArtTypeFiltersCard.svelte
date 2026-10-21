<script lang="ts">
  import type { ArtType, ServerAsset } from "../../generated/rest/types.gen";
  import { ITEM_ART_TYPES, SEASON_ART_TYPES } from "../../generated/settings";
  import { ASSET_LABELS } from "../utils/artTypes";
  import ArtTypeGroup from "./ArtTypeGroup.svelte";

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
  <div class="filter-options">
    {#each ITEM_ART_TYPES as artType (artType)}
      <label class="checkbox-group">
        <input
          type="checkbox"
          checked={artTypes.includes(artType)}
          disabled={!hasSelectedFolders}
          onchange={() => ontoggletype(artType)}
        />
        <span>{ASSET_LABELS[artType]}</span>
      </label>
    {/each}
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
  <ArtTypeGroup
    label="Shows only"
    note={hasShowFolders ? null : "select show folders to enable"}
    disabled={!hasShowFolders}
  >
    {#each SEASON_ART_TYPES as artType (artType)}
      <label class="checkbox-group">
        <input
          type="checkbox"
          checked={artTypes.includes(artType)}
          disabled={!hasSelectedFolders || !hasShowFolders}
          onchange={() => ontoggletype(artType)}
        />
        <span>{ASSET_LABELS[artType]}</span>
      </label>
    {/each}
  </ArtTypeGroup>
</div>
