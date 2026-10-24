<script lang="ts">
  import Settings from "@lucide/svelte/icons/settings";
  import WandSparkles from "@lucide/svelte/icons/wand-sparkles";
  import Users from "@lucide/svelte/icons/users";
  import { route } from "../router/routes";
  let { formId }: { formId: string } = $props();
  const sections = [
    { key: "general", label: "General", icon: Settings },
    { key: "builder", label: "Builder", icon: WandSparkles },
    { key: "members", label: "Members", icon: Users },
  ] as const;
  let active = $derived(
    sections.find((section) => route.hash === `#${formId}-${section.key}`)?.key ?? "general",
  );
</script>

{#each sections as section (section.key)}
  <a
    class={["tab-item", { active: active === section.key }]}
    href={`#${formId}-${section.key}`}
    aria-current={active === section.key ? "location" : undefined}
  >
    <section.icon size={16} /><span>{section.label}</span>
  </a>
{/each}
