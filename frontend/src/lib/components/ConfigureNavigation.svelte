<script module lang="ts">
  import Settings from "@lucide/svelte/icons/settings";
  import WandSparkles from "@lucide/svelte/icons/wand-sparkles";
  import Users from "@lucide/svelte/icons/users";
  import SlidersHorizontal from "@lucide/svelte/icons/sliders-horizontal";
  import Calendar from "@lucide/svelte/icons/calendar";

  const SECTIONS = [
    { key: "setup", label: "Setup", icon: Settings },
    { key: "content", label: "Content", icon: WandSparkles },
    { key: "members", label: "Members", icon: Users },
    { key: "settings", label: "Settings", icon: SlidersHorizontal },
    { key: "schedule", label: "Schedule", icon: Calendar },
  ] as const;
</script>

<script lang="ts">
  import type { CollectionDetail } from "../../generated/rest/types.gen";
  import { goToCollectionView, route } from "../router/routes";

  let {
    formId,
    collection,
    configuring,
  }: {
    formId: string;
    collection: CollectionDetail;
    /** The configure view is open, so one section is the current one. */
    configuring: boolean;
  } = $props();

  let active = $derived(
    configuring
      ? (SECTIONS.find((section) => route.hash === `#${formId}-${section.key}`)?.key ?? "setup")
      : null,
  );
</script>

{#each SECTIONS as section (section.key)}
  <a
    class={["tab-item", { active: active === section.key }]}
    href={`#${formId}-${section.key}`}
    onclick={(event) => {
      event.preventDefault();
      goToCollectionView(collection, "configure", "poster", `${formId}-${section.key}`);
    }}
    aria-current={active === section.key ? "location" : undefined}
  >
    <section.icon size={16} /><span>{section.label}</span>
  </a>
{/each}
