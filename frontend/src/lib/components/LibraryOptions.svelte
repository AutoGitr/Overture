<script lang="ts">
  import type { Snippet } from "svelte";
  import { librariesByServer } from "../utils/libraries.svelte";
  import Checklist from "./Checklist.svelte";

  let {
    libraries,
    selected,
    ontoggle,
    ontoggleall,
    notice,
  }: {
    libraries: readonly { id: string; title: string; server_id: number; count?: number | null }[];
    selected: readonly string[];
    ontoggle: (id: string) => void;
    /** Choose every library, or none. */
    ontoggleall: (checked: boolean) => void;
    /** Shown in place of the libraries: while loading, after an error, or when there are none. */
    notice?: Snippet;
  } = $props();
</script>

<!-- Libraries are grouped by their server, under its badge when there are several. -->
<Checklist
  label="Libraries"
  groups={librariesByServer(libraries).map((group) => ({
    key: String(group.server.id),
    label: group.label,
    serverId: group.server.id,
    options: group.libraries.map((library) => ({
      id: library.id,
      label: library.title,
      count: library.count,
      checked: selected.includes(library.id),
    })),
  }))}
  selectAllDisabled={libraries.length === 0}
  ontoggle={(_server, id) => ontoggle(id)}
  {ontoggleall}
  {notice}
/>
