<script lang="ts">
  import { onMount } from "svelte";
  import { navigate } from "../routes";

  // Matches a bare "/" as well as any unrecognized path (sv-router's "*" catch-all).
  // Bounce straight to the movies library, which is the app's default view.
  onMount(() => {
    void navigate("/movies", { replace: true });
  });
</script>
