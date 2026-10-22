<script lang="ts">
  import DetailPanel from "../../components/DetailPanel.svelte";
  import { uiState } from "../../stores/uiState.svelte";

  // This route represents "items mode, nothing selected" for whichever tab is
  // active, so the browser surface shows on mobile.
  $effect(() => {
    uiState.mobileShowDetail = false;
  });
</script>

<DetailPanel />
