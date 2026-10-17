<script lang="ts">
  import DetailPanel from "../../components/DetailPanel.svelte";
  import { collectionState } from "../../stores/collectionState.svelte";
  import { selectedState } from "../../stores/selectedState.svelte";
  import { uiState } from "../../stores/uiState.svelte";

  // This route represents "items mode, nothing selected" for whichever tab is
  // active. Clear any selection left over from a different route (e.g. the
  // user navigated here from an item or collection's detail view).
  $effect(() => {
    uiState.mobileShowDetail = false;
    if (selectedState.subject) selectedState.selectItem(null);
    if (collectionState.selectedCollection) collectionState.selectCollection(null);
  });
</script>

<DetailPanel />
