<script lang="ts">
  import { TEXT_LIMITS } from "../../generated/settings";
  import type { CollectionDimensionRead } from "../../generated/rest/types.gen";
  import type { SetGenerator } from "../utils/collectionFormShared.svelte";
  import FieldRow from "./FieldRow.svelte";
  import SetDimensionField from "./SetDimensionField.svelte";

  let {
    generator,
    dimensions,
    onchoose,
  }: {
    /** The set being set up, edited in place. */
    generator: SetGenerator;
    dimensions: CollectionDimensionRead[];
    onchoose: (dimension: CollectionDimensionRead) => void;
  } = $props();

  const id = $props.id();
</script>

<!-- What a set splits by, and how it titles each collection. -->
<SetDimensionField value={generator.dimension} {dimensions} {onchoose} />
<FieldRow
  label="Title template"
  for={`${id}-title`}
  hint={"{value} becomes each value, such as 1990 or Action."}
>
  <input
    id={`${id}-title`}
    required
    maxlength={TEXT_LIMITS.setTitleFormat}
    bind:value={generator.title_format}
    placeholder={"{value}"}
  />
</FieldRow>
