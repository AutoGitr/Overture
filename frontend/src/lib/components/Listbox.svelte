<script module lang="ts">
  export interface ListboxItem {
    key: string;
    label: string;
    detail?: string;
    selected: boolean;
    disabled?: boolean;
    group?: string;
  }
</script>

<script lang="ts">
  let {
    id,
    label,
    items,
    active,
    anchor,
    onchoose,
    onclose,
  }: {
    id: string;
    label: string;
    items: readonly ListboxItem[];
    active: number;
    anchor?: HTMLElement;
    onchoose: (index: number) => void;
    onclose: () => void;
  } = $props();

  let list: HTMLUListElement | undefined = $state();

  $effect(() => {
    if (active < 0 || !list) return;
    const item = document.getElementById(`${id}-${active}`);
    if (!item) return;
    const top = item.offsetTop;
    const bottom = top + item.offsetHeight;
    if (top < list.scrollTop) list.scrollTop = top;
    else if (bottom > list.scrollTop + list.clientHeight) {
      list.scrollTop = bottom - list.clientHeight;
    }
  });

  function positionPopover(ul: HTMLUListElement, target: HTMLElement) {
    const rect = target.getBoundingClientRect();
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    if (rect.height > 0 && (rect.bottom <= 0 || rect.top >= vh)) {
      onclose();
      return;
    }
    const gap = 2;
    const margin = 8;
    const maxWidth = Math.max(0, vw - margin * 2);
    ul.style.minWidth = `${Math.min(rect.width, maxWidth)}px`;
    ul.style.maxWidth = `${maxWidth}px`;
    const below = vh - rect.bottom - gap - margin;
    const above = rect.top - gap - margin;
    if (below >= Math.min(ul.scrollHeight, 180) || below >= above) {
      ul.style.top = `${rect.bottom + gap}px`;
      ul.style.bottom = "auto";
      ul.style.maxHeight = `${Math.min(256, Math.max(96, below))}px`;
    } else {
      ul.style.bottom = `${vh - rect.top + gap}px`;
      ul.style.top = "auto";
      ul.style.maxHeight = `${Math.min(256, Math.max(96, above))}px`;
    }
    ul.style.left = `${Math.max(margin, Math.min(rect.left, vw - margin - ul.offsetWidth))}px`;
  }

  function place(ul: HTMLUListElement) {
    if (!anchor || typeof ul.showPopover !== "function") return;
    const target = anchor;
    ul.popover = "manual";
    ul.showPopover();
    const sync = () => positionPopover(ul, target);
    const onScroll = (event: Event) => {
      if (event.target instanceof Node && ul.contains(event.target)) return;
      sync();
    };
    sync();
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", sync);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", sync);
    };
  }
</script>

<ul bind:this={list} {id} class="menu-surface" role="listbox" aria-label={label} {@attach place}>
  {#each items as item, index (item.key)}
    {#if item.group && item.group !== items[index - 1]?.group}
      <li class="caps-label group-label" role="presentation">{item.group}</li>
    {/if}
    <!-- Keep focus on the combobox trigger while choosing an option. -->
    <li
      id={`${id}-${index}`}
      role="option"
      aria-selected={item.selected}
      aria-disabled={item.disabled || undefined}
      class={["menu-option", { active: index === active }]}
      onpointerdown={(event) => event.preventDefault()}
      onclick={() => {
        if (!item.disabled) onchoose(index);
      }}
      onkeydown={(event) => {
        if ((event.key === "Enter" || event.key === " ") && !item.disabled) onchoose(index);
      }}
    ><span>{item.label}</span>{#if item.detail}<span class="detail">{item.detail}</span>{/if}</li>
  {/each}
</ul>

<style>
  ul {
    position: absolute;
    inset-inline: 0;
    top: calc(100% + 2px);
    max-height: 16rem;
    margin: 0;
    overflow-x: hidden;
    overflow-y: auto;
    overscroll-behavior: contain;
    list-style: none;
  }

  ul:popover-open {
    position: fixed;
    inset: auto;
    margin: 0;
  }

  .group-label {
    padding: var(--space-2) var(--space-3) var(--space-1);
  }

  .menu-option {
    justify-content: space-between;
  }

  .detail {
    flex-shrink: 0;
    color: var(--text-tertiary);
    font-weight: 400;
  }
</style>
