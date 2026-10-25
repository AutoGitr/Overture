<script lang="ts">
  import type { DynamicTmdbGroupConfigInput } from "../../generated/rest/types.gen";
  import { splitIds } from "../utils/collectionBuilders";
  let { config }: { config: DynamicTmdbGroupConfigInput } = $props();
</script>

<label class="form-label">
  Strip prefix
  <input maxlength="100" bind:value={config.strip_prefix} placeholder="The " />
  <span class="hint">Remove the beginning of each franchise name.</span>
</label>
<label class="form-label">
  Strip suffix
  <input maxlength="100" bind:value={config.strip_suffix} placeholder=" Collection" />
  <span class="hint">For example, The Matrix Collection becomes Matrix.</span>
</label>
<label class="form-row form-wide">
  <input type="checkbox" bind:checked={config.auto_exclude_from_other_collections} />
  Auto-exclude franchise movies from other collections
</label>
<label class="form-label form-wide">
  Exclude TMDB franchise IDs
  <input
    placeholder="e.g. 10, 86311"
    value={(config.exclude_tmdb_ids ?? []).join(", ")}
    onchange={(event) => (config.exclude_tmdb_ids = splitIds(event.currentTarget.value))}
  />
  <span class="hint">Comma-separated TMDB collection IDs to skip.</span>
</label>
