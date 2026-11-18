<script lang="ts">
  /** A view whose drawing fails, as one with a bug does. */
  function fail(): string {
    throw new Error("The view broke");
  }
</script>

<p>{fail()}</p>
