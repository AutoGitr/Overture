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
