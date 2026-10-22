<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { untrack } from "svelte";
  import { blockNavigation } from "sv-router";
  import { getLibrariesOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import DataStatus from "../../components/DataStatus.svelte";
  import { navigate } from "../routes";

  let leaving = false;
  const movies = createQuery(() => getLibrariesOptions({ query: { media_type: "movie" } }));
  const shows = createQuery(() => getLibrariesOptions({ query: { media_type: "show" } }));

  // Navigation starts before a lazy route finishes loading and changes pathname.
  $effect(() =>
    blockNavigation(() => {
      leaving = true;
      return true;
    }),
  );

  $effect(() => {
    if (leaving || !movies.isSuccess || !shows.isSuccess) return;
    const destination = movies.data.length === 0 && shows.data.length > 0 ? "/shows" : "/movies";
    untrack(() => {
      void navigate(destination, { replace: true });
    });
  });
</script>

<DataStatus
  label="libraries"
  error={movies.error ?? shows.error}
  loading={movies.isFetching || shows.isFetching}
  hasData={movies.isSuccess && shows.isSuccess}
  onretry={() => {
    void movies.refetch();
    void shows.refetch();
  }}
/>
