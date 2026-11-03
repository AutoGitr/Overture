<script lang="ts">
  import DetailPanel from "../../components/DetailPanel.svelte";
  import { uiState } from "../../stores/uiState.svelte";

  $effect(() => {
    uiState.mobileShowDetail = false;
  });
</script>

<DetailPanel />
