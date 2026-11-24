<script lang="ts">
  import type { CollectionDimensionRead, SetDimension } from "../../generated/rest/types.gen";
  import { DIMENSION_LABELS } from "../../generated/settings";
  import FieldRow from "./FieldRow.svelte";
  import Select from "./Select.svelte";

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
  let options = $derived(
    dimensions.map((entry) => ({
      value: entry.dimension,
      label: `${entry.label}${entry.smart_only ? " (Plex smart)" : ""}`,
    })),
  );
</script>

<FieldRow
  label="Split by"
  for={`${id}-dimension`}
  hint={current?.smart_only ? "Only Plex knows these values." : undefined}
>
  <Select
    id={`${id}-dimension`}
    {options}
    placeholder={`${DIMENSION_LABELS[value]} (not offered for these libraries)`}
    bind:value={
      () => value,
      (dimension) => {
        const chosen = dimensions.find((entry) => entry.dimension === dimension);
        if (chosen) onchoose(chosen);
      }
    }
  />
</FieldRow>
