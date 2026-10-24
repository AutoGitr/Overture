<script lang="ts">
  import type { Snippet } from "svelte";
  let { title, description, children }: { title: string; description: string; children: Snippet } =
    $props();
</script>

<section class="detail-section" aria-label={title}>
  <header>
    <h3>{title}</h3>
    <p class="text-muted">{description}</p>
  </header>
  <div class="section-body">{@render children()}</div>
</section>

<style>
  .detail-section {
    border: var(--border-subtle);
    border-radius: var(--radius-lg);
    background: var(--bg-secondary);
    overflow: hidden;
  }
  header {
    padding: var(--space-4);
    border-bottom: var(--border-subtle);
  }
  h3 {
    margin: 0 0 var(--space-2);
    font-size: var(--text-lg);
  }
  p {
    margin: 0;
    font-size: var(--text-sm);
  }
  .section-body {
    padding: var(--section-padding, var(--space-4));
  }
</style>
