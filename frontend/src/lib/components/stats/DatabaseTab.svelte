<script lang="ts">
  import Database from "@lucide/svelte/icons/database";
  import HardDrive from "@lucide/svelte/icons/hard-drive";
  import type { StatsResponse } from "../../../generated/rest/types.gen";
  import { formatBytes, formatDateInTimezone } from "../../utils/popupFormat";
  import Metric from "../Metric.svelte";
  import MetricGrid from "../MetricGrid.svelte";

  let { stats }: { stats: StatsResponse } = $props();
</script>

<section class="option-card">
  <div class="section-title-row">
    <span class="accent"><Database size={16} /></span>
    <span class="form-label">SQLite Engine & Storage</span>
  </div>
  <MetricGrid>
    <Metric label="Database file" value={formatBytes(stats.database.file_size_bytes)} />
    {#if stats.database.wal_size_bytes > 0}
      <Metric label="WAL File" value={formatBytes(stats.database.wal_size_bytes)} />
    {/if}
    <Metric label="Total DB Footprint" value={formatBytes(stats.database.total_size_bytes)} />
    <Metric label="Pages" value={stats.database.page_count.toLocaleString()} detail={`${stats.database.page_size} B/page`} />
    <Metric label="Freelist / Free" value={formatBytes(stats.database.free_size_bytes)} detail={`${stats.database.freelist_count} pages`} />
  </MetricGrid>
</section>

<section class="option-card">
  <span class="form-label">Database Tables ({stats.database.tables.length})</span>
  <div class="table-container">
    <table class="stats-table">
      <thead>
        <tr>
          <th>Table</th>
          <th>Description</th>
          <th class="numeric">Rows</th>
        </tr>
      </thead>
      <tbody>
        {#each stats.database.tables as table (table.table_name)}
          <tr>
            <td><code class="table-name">{table.table_name}</code></td>
            <td>{table.description}</td>
            <td class="numeric count">{table.row_count.toLocaleString()}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

<section class="option-card">
  <div class="section-title-row">
    <span class="accent"><HardDrive size={16} /></span>
    <span class="form-label">Backups</span>
  </div>
  <MetricGrid>
    <Metric label="Total backups" value={String(stats.backups.total_backups)} />
    <Metric label="Backup storage" value={formatBytes(stats.backups.total_size_bytes)} />
    <Metric label="Latest backup" value={stats.backups.latest_backup_at
        ? formatDateInTimezone(stats.backups.latest_backup_at, "UTC")
        : "None"} />
  </MetricGrid>
</section>

<style>





  .section-title-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .accent {
    display: inline-flex;
    color: var(--accent);
  }

  .table-container {
    overflow-x: auto;
    margin-top: var(--space-2);
  }

  .stats-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-xs);
  }

  .stats-table th {
    text-align: left;
    padding: var(--space-2) var(--space-3);
    color: var(--text-tertiary);
    border-bottom: var(--border-muted);
    font-weight: 500;
  }

  .stats-table td {
    padding: var(--space-2) var(--space-3);
    border-bottom: var(--border-subtle);
    color: var(--text-secondary);
  }

  .table-name {
    font-family: var(--font-mono);
    color: var(--accent);
    font-size: var(--text-xs);
  }

  .stats-table .numeric {
    text-align: right;
  }

  .stats-table .count {
    font-family: var(--font-mono);
    font-weight: 600;
    color: var(--text-primary);
  }
</style>
