<script lang="ts">
  import GripVertical from "@lucide/svelte/icons/grip-vertical";

  let {
    sourceOrder,
    selectedSources,
    labels,
    disabledSources = [],
    storageKey,
    ontoggle,
    onmove,
  }: {
    sourceOrder: string[];
    selectedSources: string[];
    labels: Record<string, string>;
    /** Catalog sources, unavailable while OvertureDB is off. */
    disabledSources?: readonly string[];
    storageKey: string;
    ontoggle: (source: string) => void;
    onmove: (source: string, target: string) => void;
  } = $props();

  let draggedSource = $state<string | null>(null);
  let pointerDragSource = $state<string | null>(null);
  let pointerDragId = $state<number | null>(null);
  let pointerDragStartY = $state(0);

  function sourceDisabled(source: string) {
    return disabledSources.includes(source);
  }

  function resetPointerDrag() {
    pointerDragSource = null;
    pointerDragId = null;
    pointerDragStartY = 0;
  }

  function handlePointerDown(source: string, event: PointerEvent) {
    if (sourceDisabled(source) || event.button !== 0) return;
    pointerDragSource = source;
    pointerDragId = event.pointerId;
    pointerDragStartY = event.clientY;
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent) {
    if (pointerDragId !== event.pointerId || !pointerDragSource) return;
    if (Math.abs(event.clientY - pointerDragStartY) < 8) return;
    event.preventDefault();

    const target = sourceOrder.find((candidate) => {
      if (candidate === pointerDragSource) return false;
      const element = document.querySelector<HTMLElement>(
        `[data-source-order="${storageKey}-${candidate}"]`,
      );
      if (!element) return false;
      const rect = element.getBoundingClientRect();
      return event.clientY >= rect.top && event.clientY <= rect.bottom;
    });
    if (target && !sourceDisabled(target)) onmove(pointerDragSource, target);
  }

  function handlePointerEnd(event: PointerEvent) {
    if (pointerDragId === event.pointerId) resetPointerDrag();
  }

  function handleDragStart(source: string, event: DragEvent) {
    if (sourceDisabled(source)) return;
    draggedSource = source;
    event.dataTransfer?.setData("text/plain", source);
    if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
  }

  function handleDrop(target: string, event: DragEvent) {
    event.preventDefault();
    const source = draggedSource || event.dataTransfer?.getData("text/plain");
    draggedSource = null;
    if (source && !sourceDisabled(source)) onmove(source, target);
  }
</script>

<div class="source-list" role="list">
  {#each sourceOrder as source (source)}
    {@const disabled = sourceDisabled(source)}
    <div
      class="source-row"
      class:source-row-disabled={disabled}
      class:source-row-dragging={pointerDragSource === source}
      data-source-order={storageKey + "-" + source}
      role="listitem"
      draggable={!disabled}
      ondragstart={(event) => handleDragStart(source, event)}
      ondragover={(event) => event.preventDefault()}
      ondrop={(event) => handleDrop(source, event)}
      ondragend={() => (draggedSource = null)}
    >
      <button
        type="button"
        class="source-handle-button"
        aria-label="Drag source"
        {disabled}
        onpointerdown={(event) => handlePointerDown(source, event)}
        onpointermove={handlePointerMove}
        onpointerup={handlePointerEnd}
        onpointercancel={handlePointerEnd}
      >
        <GripVertical size={15} class="source-handle" />
      </button>
      <label class="checkbox-group source-checkbox">
        <input
          type="checkbox"
          checked={selectedSources.includes(source) && !disabled}
          {disabled}
          onchange={() => ontoggle(source)}
        />
        <span>
          {labels[source] ?? source}
          {#if disabled}
            <span class="muted-text">- enable OvertureDB first</span>
          {/if}
        </span>
      </label>
    </div>
  {/each}
</div>

<style>
  .source-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }

  .source-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2);
    border: var(--border-subtle);
    border-radius: var(--radius-sm);
    background: var(--bg-secondary);
    cursor: grab;
  }

  .source-row:active {
    cursor: grabbing;
  }

  .source-row-disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .source-row-dragging {
    border-color: oklch(from var(--accent) l c h / 0.45);
    background: var(--bg-tertiary);
  }

  .source-handle-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    border-radius: var(--radius-sm);
    color: var(--text-tertiary);
    cursor: grab;
    touch-action: none;
    flex-shrink: 0;
  }

  .source-handle-button:active {
    cursor: grabbing;
  }

  .source-handle-button:disabled {
    cursor: not-allowed;
  }

  :global(.source-handle) {
    color: var(--text-tertiary);
    flex-shrink: 0;
  }

  .source-checkbox {
    flex: 1;
  }
</style>
