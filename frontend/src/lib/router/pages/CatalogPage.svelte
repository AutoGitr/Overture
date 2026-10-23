<script lang="ts">
  import CatalogDetailPanel from "../../components/CatalogDetailPanel.svelte";
  import { uiState } from "../../stores/uiState.svelte";

  $effect(() => {
    uiState.mobileShowDetail = false;
  });
</script>

<CatalogDetailPanel />
