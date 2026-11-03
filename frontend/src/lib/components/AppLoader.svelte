<script lang="ts">
  import ProductBrand from "./ProductBrand.svelte";
</script>

<div class="app-loader" role="status" aria-label="Loading Overture">
  <div class="app-loader-brand">
    <ProductBrand size="lg" />
  </div>
  <div class="loader-spinner"></div>
</div>

<style>
  .app-loader {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    height: 100dvh;
    gap: var(--space-6);
    background: var(--bg-root);
  }

  .app-loader-brand {
    font-size: var(--text-3xl);
  }

  .loader-spinner {
    width: 24px;
    height: 24px;
    border: 2px solid var(--bg-hover);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
</style>
