<script lang="ts">
  import Settings from "@lucide/svelte/icons/settings";
  import WandSparkles from "@lucide/svelte/icons/wand-sparkles";
  import Users from "@lucide/svelte/icons/users";
  import Eye from "@lucide/svelte/icons/eye";
  import Calendar from "@lucide/svelte/icons/calendar";
  import { route } from "../router/routes";
  import { CollectionDraft, type CollectionEditor } from "../utils/collectionForms.svelte";
  let { formId, editor }: { formId: string; editor: CollectionEditor | CollectionDraft } = $props();
  let set = $derived(editor instanceof CollectionDraft && editor.kind === "set");
  let sections = $derived(
    set
      ? [
          { key: "setup", label: "Setup", icon: Settings },
          { key: "content", label: "Collections", icon: WandSparkles },
          { key: "display", label: "Defaults", icon: Eye },
        ]
      : [
          { key: "setup", label: "Setup", icon: Settings },
          { key: "content", label: "Content", icon: WandSparkles },
          ...(editor.creating ? [] : [{ key: "members", label: "Members", icon: Users }]),
          { key: "display", label: "Display", icon: Eye },
          { key: "schedule", label: "Schedule", icon: Calendar },
        ],
  );
  let active = $derived(
    sections.find((section) => route.hash === `#${formId}-${section.key}`)?.key ?? "setup",
  );
</script>

{#each sections as section (section.key)}
  <a
    class={["tab-item", { active: active === section.key }]}
    href={`#${formId}-${section.key}`}
    onclick={() =>
      document
        .getElementById(`${formId}-${section.key}`)
        ?.querySelector<HTMLButtonElement>('button[aria-expanded="false"]')
        ?.click()}
    aria-current={active === section.key ? "location" : undefined}
  >
    <section.icon size={16} /><span>{section.label}</span>
  </a>
{/each}
