<script lang="ts">
  import Search from "@lucide/svelte/icons/search";
  import { createQuery } from "@tanstack/svelte-query";
  import {
    searchMdblistListsOptions,
    searchTmdbOptions,
    searchTmdbPeopleOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { MediaType } from "../../generated/rest/types.gen";
  import { errorMessage } from "../utils/errors";

  /**
   * Find what a source names by searching for it. A person or franchise is
   * chosen, and its ID is the field's value; titles and lists are added to
   * the ones the condition names already, which their own input holds.
   */
  let {
    kind,
    label,
    id = 0,
    mediaType = "movie",
    onpick,
    onclear,
  }: {
    kind: "person" | "franchise" | "title" | "mdblist";
    label: string;
    id?: number;
    mediaType?: MediaType;
    onpick: (id: number, name: string | null) => void;
    onclear?: () => void;
  } = $props();

  const ID = /^\s*[1-9]\d*\s*$/;
  let chooses = $derived(kind === "person" || kind === "franchise");
  let text = $derived(chooses && id ? String(id) : "");
  let submitted = $state("");
  let picked = $state<string | null>(null);
  const people = createQuery(() => ({
    ...searchTmdbPeopleOptions({ query: { query: submitted } }),
    enabled: kind === "person" && !!submitted,
  }));
  const titles = createQuery(() => ({
    ...searchTmdbOptions({
      query: { query: submitted, media_type: kind === "title" ? mediaType : "movie" },
    }),
    enabled: (kind === "franchise" || kind === "title") && !!submitted,
  }));
  const lists = createQuery(() => ({
    ...searchMdblistListsOptions({ query: { query: submitted } }),
    enabled: kind === "mdblist" && !!submitted,
  }));
  let search = $derived(kind === "person" ? people : kind === "mdblist" ? lists : titles);
  let results = $derived.by(() => {
    switch (kind) {
      case "person":
        return (people.data?.results ?? []).map((person) => ({
          id: person.tmdb_id,
          name: person.name,
          detail: person.known_for_department,
        }));
      case "mdblist":
        return (lists.data ?? []).map((list) => ({
          id: list.id,
          name: list.name,
          detail: [list.owner, list.items === null ? null : `${list.items} titles`]
            .filter(Boolean)
            .join(", "),
        }));
      default:
        return (titles.data?.results ?? []).flatMap((result) =>
          (result.kind === "collection") === (kind === "franchise")
            ? [
                {
                  id: result.tmdb_id,
                  name: result.title,
                  detail: result.kind === "item" && result.year ? String(result.year) : null,
                },
              ]
            : [],
        );
    }
  });
  let noun = $derived(
    {
      person: "TMDB person",
      franchise: "TMDB franchise",
      title: mediaType === "show" ? "TMDB show" : "TMDB movie",
      mdblist: "MDBList list",
    }[kind],
  );
  let placeholder = $derived(
    {
      person: "Search TMDB people, or a person ID",
      franchise: "Search TMDB franchises, or a franchise ID",
      title: `Search TMDB ${mediaType === "show" ? "shows" : "movies"} to add`,
      mdblist: "Search MDBList lists to add",
    }[kind],
  );

  function submit() {
    submitted = text.trim();
  }
</script>

<div class="picker">
  <div class="search">
    {#if chooses}
      <input
        required={!onclear}
        pattern="\s*[1-9][0-9]*\s*"
        title={`Pick a search result or enter a ${noun} ID`}
        aria-label={`${label} ${noun} ID`}
        {placeholder}
        value={text}
        oninput={(event) => {
          text = event.currentTarget.value;
          picked = null;
          if (ID.test(text)) onpick(Number(text), null);
          else if (!text.trim()) onclear?.();
        }}
        onkeydown={(event) => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          submit();
        }}
      />
    {:else}
      <input
        type="search"
        aria-label={`Search ${label} ${noun}s`}
        {placeholder}
        value={text}
        oninput={(event) => (text = event.currentTarget.value)}
        onkeydown={(event) => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          submit();
        }}
      />
    {/if}
    <button
      type="button"
      class="btn btn-ghost btn-sm btn-icon"
      aria-label={`Search ${label}`}
      disabled={!text.trim()}
      onclick={submit}><Search size={14} /></button
    >
  </div>
  {#if picked}<span class="hint">{picked}</span>{/if}
  {#if search.error}
    <p class="hint" role="alert">{errorMessage(search.error, "Search failed")}</p>
  {:else if submitted && search.isSuccess && !results.length}
    <p class="hint">No matches.</p>
  {:else if submitted && results.length}
    <ul aria-label={`${label} results`}>
      {#each results.slice(0, 8) as result (result.id)}
        <li>
          <button
            type="button"
            class="btn btn-ghost btn-sm"
            onclick={() => {
              onpick(result.id, result.name);
              if (chooses) text = String(result.id);
              picked = chooses ? result.name : `Added ${result.name}`;
              submitted = "";
            }}
            >{chooses ? "" : "Add "}{result.name}{#if result.detail}<span class="hint">
                &middot; {result.detail}</span
              >{/if}</button
          >
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .picker,
  ul {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }

  .search {
    display: flex;
    gap: var(--space-1);
  }

  .search input {
    flex: 1;
    min-width: 0;
  }

  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  li .btn {
    justify-content: flex-start;
    width: 100%;
    text-align: left;
  }
</style>
