<script lang="ts">
  import { THEME_SOURCE_LABELS } from "../../generated/settings";
  import SourceOrderList from "./SourceOrderList.svelte";

  let {
    themeSourceOrder,
    selectedThemeSources,
    disabledSources,
    ontogglesource,
    onmovesource,
  }: {
    themeSourceOrder: string[];
    selectedThemeSources: string[];
    disabledSources: readonly string[];
    ontogglesource: (source: string) => void;
    onmovesource: (source: string, target: string) => void;
  } = $props();
</script>

<div class="option-card workflow-card">
  <div class="workflow-header">
    <span class="form-label">Themes</span>
  </div>
  <div class="asset-section">
    <span class="form-label">Sources</span>
    <p class="option-note">
      Tried top to bottom; the first match wins. YouTube searches use the Theme Search Query from
      Settings.
    </p>
    <SourceOrderList
      sourceOrder={themeSourceOrder}
      selectedSources={selectedThemeSources}
      labels={THEME_SOURCE_LABELS}
      {disabledSources}
      storageKey="theme"
      ontoggle={ontogglesource}
      onmove={onmovesource}
    />
  </div>
</div>
