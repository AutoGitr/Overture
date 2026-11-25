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

  /** A section of a collection's or a group's configuration. */
  export type ConfigureSection = (typeof SECTIONS)[number]["key"];
</script>

<script lang="ts">
  import { route } from "../router/routes";
  import { revealSection } from "../utils/revealSection";

  let {
    formId,
    configuring,
    sections = SECTIONS.map((section) => section.key),
    onopen,
  }: {
    formId: string;
    /** The configure view is open, so one section is the current one. */
    configuring: boolean;
    /** The sections the form holds. */
    sections?: readonly ConfigureSection[];
    /** Open the configure view at the section the target names. */
    onopen: (target: string) => void;
  } = $props();

  let shown = $derived(SECTIONS.filter((section) => sections.includes(section.key)));
  let active = $derived(
    configuring
      ? (shown.find((section) => route.hash === `#${formId}-${section.key}`)?.key ?? "setup")
      : null,
  );
</script>

{#each shown as section (section.key)}
  <a
    class={["tab-item", { active: active === section.key }]}
    href={`#${formId}-${section.key}`}
    onclick={(event) => {
      event.preventDefault();
      const target = `${formId}-${section.key}`;
      // The URL already names it, so no navigation follows: jump again directly.
      if (configuring && route.hash === `#${target}`) void revealSection(target);
      else onopen(target);
    }}
    aria-current={active === section.key ? "location" : undefined}
    aria-label={section.label}
    title={section.label}
  >
    <section.icon size={16} />
  </a>
{/each}
