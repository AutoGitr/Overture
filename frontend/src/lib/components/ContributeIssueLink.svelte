<script lang="ts">
  import githubIcon from "../../assets/icons/github.svg";
  import type { ContributionIssue } from "../../generated/rest/types.gen";
  import IdBadge from "./IdBadge.svelte";

  /** Opens the OvertureDB issue that contributes one entry, filled in. */
  let { issue }: { issue: ContributionIssue | null | undefined } = $props();
  let title = $derived(
    ["Contribute to OvertureDB on GitHub", ...(issue?.notes ?? [])].join("\n"),
  );
</script>

{#if issue?.url}
  <IdBadge
    href={issue.url}
    {title}
    icon={githubIcon}
    alt="GitHub"
    --id-badge-icon-filter="var(--mono-logo-filter)"
  />
{/if}
