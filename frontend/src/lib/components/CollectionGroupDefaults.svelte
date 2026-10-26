<script lang="ts">
  import type {
    CollectionCapabilities,
    CollectionGroupPolicyInput,
    CollectionPolicyBase,
  } from "../../generated/rest/types.gen";
  import { availableOrders } from "../utils/collectionCriteria";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";

  let {
    policy,
    defaults,
    capabilities,
    smart = false,
  }: {
    policy: CollectionGroupPolicyInput;
    /** Global defaults, shown as placeholders. */
    defaults: CollectionPolicyBase | undefined;
    capabilities: CollectionCapabilities | undefined;
    /** Its collection set creates smart collections, which Plex sorts. */
    smart?: boolean;
  } = $props();

  const id = $props.id();
</script>

<CollectionPolicyFields
  {policy}
  {defaults}
  plex={capabilities?.visibility ?? false}
  orders={availableOrders(capabilities, smart)}
/>

<div class="form-label">
  <label for={`${id}-sort-title`}>Sort title</label>
  <input
    id={`${id}-sort-title`}
    maxlength="400"
    value={policy.sort_title_format ?? ""}
    placeholder={defaults?.sort_title_format || "Default"}
    oninput={(event) => (policy.sort_title_format = event.currentTarget.value || null)}
  />
  <span class="hint"
    >A template with &#123;title&#125; and &#123;group&#125;, such as 01_&#123;title&#125;, keeps
    the group together. Blank uses the global default.</span
  >
</div>
<div class="form-label">
  <label for={`${id}-summary`}>Summary</label>
  <input
    id={`${id}-summary`}
    maxlength="2000"
    value={policy.summary_format ?? ""}
    placeholder={defaults?.summary_format || "Default"}
    oninput={(event) => (policy.summary_format = event.currentTarget.value || null)}
  />
  <span class="hint"
    >Tokens: &#123;title&#125;, &#123;group&#125;, &#123;start_date&#125;, &#123;end_date&#125;,
    &#123;summary&#125;.</span
  >
</div>
<div class="form-label">
  <label for={`${id}-start`}>Active from (MM-DD)</label>
  <input
    id={`${id}-start`}
    maxlength="5"
    placeholder={defaults?.active_start_mmdd ?? "All year"}
    value={policy.active_start_mmdd ?? ""}
    oninput={(event) => (policy.active_start_mmdd = event.currentTarget.value.trim() || null)}
  />
</div>
<div class="form-label">
  <label for={`${id}-end`}>Active until (MM-DD)</label>
  <input
    id={`${id}-end`}
    maxlength="5"
    placeholder={defaults?.active_end_mmdd ?? "All year"}
    value={policy.active_end_mmdd ?? ""}
    oninput={(event) => (policy.active_end_mmdd = event.currentTarget.value.trim() || null)}
  />
</div>
<label class="form-label">
  Sync interval (hours)
  <input
    type="number"
    min="1"
    max="8760"
    placeholder="Default"
    value={policy.sync_interval_hours ?? ""}
    oninput={(event) =>
      (policy.sync_interval_hours = event.currentTarget.value
        ? event.currentTarget.valueAsNumber
        : null)}
  />
</label>
<label class="form-label">
  Scheduled sync
  <select bind:value={policy.sync_enabled}>
    <option value={null}>Default</option>
    <option value={true}>Enabled</option>
    <option value={false}>Disabled</option>
  </select>
</label>
