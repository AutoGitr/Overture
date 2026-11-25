<script lang="ts">
  import CollectionGroupManager from "../../components/CollectionGroupManager.svelte";
  import DataStatus from "../../components/DataStatus.svelte";
  import { allLibraries } from "../../utils/libraries.svelte";
  import { routedGroup } from "../routes";

  const libraries = allLibraries();
  let group = $derived(routedGroup());
</script>

<DataStatus
  label="libraries"
  error={libraries.error}
  loading={libraries.isFetching}
  hasData={libraries.data !== undefined}
  onretry={() => libraries.refetch()}
/>
{#if group !== null}
  <!-- Each group gets its own form, so another's edits never carry over. -->
  {#key group}<CollectionGroupManager {group} libraries={libraries.data ?? []} />{/key}
{/if}
