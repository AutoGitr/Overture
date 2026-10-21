<script lang="ts">
  import Database from "@lucide/svelte/icons/database";
  import HardDrive from "@lucide/svelte/icons/hard-drive";
  import type { StatsResponse } from "../../../generated/rest/types.gen";
  import { formatBytes, formatDateInTimezone } from "../../utils/popupFormat";

  let { stats }: { stats: StatsResponse } = $props();
</script>

{#snippet metric(label: string, value: string, detail: string | null = null)}
  <div class="metric-item">
    <span class="metric-label">{label}</span>
    <span class="metric-val">
      {value}
      {#if detail}
        <span class="dimmed">({detail})</span>
      {/if}
    </span>
  </div>
{/snippet}

<section class="option-card">
  <div class="section-title-row">
    <span class="accent"><Database size={16} /></span>
    <span class="form-label mb-0">SQLite Engine & Storage</span>
  </div>
  <div class="metrics-row">
    {@render metric("Database File", formatBytes(stats.database.file_size_bytes))}
    {#if stats.database.wal_size_bytes > 0}
      {@render metric("WAL File", formatBytes(stats.database.wal_size_bytes))}
    {/if}
    {@render metric("Total DB Footprint", formatBytes(stats.database.total_size_bytes))}
    {@render metric(
      "Pages",
      stats.database.page_count.toLocaleString(),
      `${stats.database.page_size} B/page`,
    )}
    {@render metric(
      "Freelist / Free",
      formatBytes(stats.database.free_size_bytes),
      `${stats.database.freelist_count} pages`,
    )}
  </div>
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
    <span class="form-label mb-0">Backups</span>
  </div>
  <div class="metrics-row">
    {@render metric("Total Backups", String(stats.backups.total_backups))}
    {@render metric("Backup Storage", formatBytes(stats.backups.total_size_bytes))}
    {@render metric(
      "Latest Backup",
      stats.backups.latest_backup_at
        ? formatDateInTimezone(stats.backups.latest_backup_at, "UTC")
        : "None",
    )}
  </div>
</section>

<style>
  .metrics-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--space-3);
  }

  .metric-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .metric-label {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }

  .metric-val {
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-primary);
  }

  .dimmed {
    color: var(--text-tertiary);
    font-size: var(--text-xs);
    font-weight: normal;
  }

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
