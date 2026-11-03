<script lang="ts">
  import Search from "@lucide/svelte/icons/search";
  import { createQuery } from "@tanstack/svelte-query";
  import {
    searchTmdbOptions,
    searchTmdbPeopleOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { errorMessage } from "../utils/errors";

  let {
    kind,
    label,
    id,
    onpick,
  }: {
    /** What to find: a person, or a movie franchise. */
    kind: "person" | "franchise";
    /** Names the field for assistive technology. */
    label: string;
    /** The chosen TMDB ID, 0 while none is. */
    id: number;
    /** A result was picked, or an ID typed; a typed ID has no name. */
    onpick: (tmdbId: number, name: string | null) => void;
  } = $props();

  const ID = /^\s*[1-9]\d*\s*$/;
  /** What the field shows: the chosen ID, or a search being typed. */
  let text = $derived(id ? String(id) : "");
  /** The search runs when submitted, not on every keystroke. */
  let submitted = $state("");
  let picked = $state<string | null>(null);
  const people = createQuery(() => ({
    ...searchTmdbPeopleOptions({ query: { query: submitted } }),
    enabled: kind === "person" && !!submitted,
  }));
  const franchises = createQuery(() => ({
    ...searchTmdbOptions({ query: { query: submitted, media_type: "movie" } }),
    enabled: kind === "franchise" && !!submitted,
  }));
  let search = $derived(kind === "person" ? people : franchises);
  let results = $derived(
    kind === "person"
      ? (people.data?.results ?? []).map((person) => ({
          id: person.tmdb_id,
          name: person.name,
          detail: person.known_for_department,
        }))
      : (franchises.data?.results ?? []).flatMap((result) =>
          result.kind === "collection"
            ? [{ id: result.tmdb_id, name: result.title, detail: null }]
            : [],
        ),
  );
  let noun = $derived(kind === "person" ? "person" : "franchise");

  function submit() {
    submitted = text.trim();
  }
</script>

<div class="picker">
  <div class="search">
    <input
      required
      pattern="\s*[1-9][0-9]*\s*"
      title={`Pick a search result or enter a TMDB ${noun} ID`}
      aria-label={`${label} TMDB ${noun} ID`}
      placeholder={kind === "person"
        ? "Search TMDB people, or a person ID"
        : "Search TMDB franchises, or a franchise ID"}
      value={text}
      oninput={(event) => {
        text = event.currentTarget.value;
        picked = null;
        if (ID.test(text)) onpick(Number(text), null);
      }}
      onkeydown={(event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        submit();
      }}
    />
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
    <p class="hint" role="alert">{errorMessage(search.error, "TMDB search failed")}</p>
  {:else if submitted && search.isSuccess && !results.length}
    <p class="hint">No matches on TMDB.</p>
  {:else if submitted && results.length}
    <ul aria-label={`${label} results`}>
      {#each results.slice(0, 8) as result (result.id)}
        <li>
          <button
            type="button"
            class="btn btn-ghost btn-sm"
            onclick={() => {
              onpick(result.id, result.name);
              text = String(result.id);
              picked = result.name;
              submitted = "";
            }}
            >{result.name}{#if result.detail}<span class="hint">
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
