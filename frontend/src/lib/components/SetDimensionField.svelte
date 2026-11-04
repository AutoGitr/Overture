<script lang="ts">
  import type { CollectionDimensionRead, SetDimension } from "../../generated/rest/types.gen";
  import FieldRow from "./FieldRow.svelte";

  /** What a set makes one collection per value of. */
  let {
    value,
    dimensions,
    onchoose,
  }: {
    value: SetDimension;
    dimensions: CollectionDimensionRead[];
    onchoose: (dimension: CollectionDimensionRead) => void;
  } = $props();

  const id = $props.id();
  let current = $derived(dimensions.find((entry) => entry.dimension === value));
</script>

<FieldRow
  label="Split by"
  for={`${id}-dimension`}
  hint={current?.smart_only ? "Only Plex knows these values." : undefined}
>
  <select
    id={`${id}-dimension`}
    {value}
    onchange={(event) => {
      const chosen = dimensions.find((entry) => entry.dimension === event.currentTarget.value);
      if (chosen) onchoose(chosen);
    }}
  >
    {#if !current}
      <option {value} disabled>Unavailable here</option>
    {/if}
    {#each dimensions as entry (entry.dimension)}
      <option value={entry.dimension}>{entry.label}{entry.smart_only ? " (Plex smart)" : ""}</option
      >
    {/each}
  </select>
</FieldRow>
