<script lang="ts">
  interface Props {
    as?: "h1" | "span" | "div" | "a";
    size?: "md" | "lg";
    class?: string;
    href?: string;
    target?: string;
  }

  let { as = "span", size = "md", class: className = "", href, target }: Props = $props();
</script>

{#snippet brandContent()}
  <img src="/brand/overture-logo-inline.svg" width="640" height="128" alt="" aria-hidden="true" />
  <span class="sr-only">Overture</span>
{/snippet}

{#if href}
  {#if as === "span" || as === "a"}
    <a {href} {target} class={`product-brand ${size} ${className}`.trim()} aria-label="Overture">
      {@render brandContent()}
    </a>
  {:else}
    <svelte:element this={as} class="product-brand-heading">
      <a {href} {target} class={`product-brand ${size} ${className}`.trim()} aria-label="Overture">
        {@render brandContent()}
      </a>
    </svelte:element>
  {/if}
{:else}
  <svelte:element
    this={as}
    class={`product-brand ${size} ${className}`.trim()}
    aria-label="Overture"
  >
    {@render brandContent()}
  </svelte:element>
{/if}

<style>
  .product-brand {
    display: inline-flex;
    align-items: center;
    line-height: 1;
    -webkit-user-select: none;
    user-select: none;
  }

  .product-brand img {
    width: 6.5em;
    height: 1.3em;
    flex: none;
  }

  .product-brand.md {
    font-size: var(--text-xl);
  }

  .product-brand.lg {
    font-size: var(--text-3xl);
  }

  .product-brand-heading {
    display: inline-flex;
    align-items: center;
    font-size: inherit;
    font-weight: inherit;
    line-height: inherit;
    margin: 0;
  }

  a.product-brand {
    text-decoration: none;
    cursor: pointer;
  }

  a.product-brand:hover {
    opacity: 0.8;
  }

  a.product-brand:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: var(--radius-sm);
  }
</style>
