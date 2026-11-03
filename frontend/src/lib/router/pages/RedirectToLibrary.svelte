<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { untrack } from "svelte";
  import { blockNavigation } from "sv-router";
  import {
    getLibrariesOptions,
    getSettingsOptions,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import DataStatus from "../../components/DataStatus.svelte";
  import { CatalogBrowsing } from "../../utils/catalogBrowsing.svelte";
  import { navigate } from "../routes";

  let leaving = false;
  const settings = createQuery(() => getSettingsOptions());
  const movies = createQuery(() => getLibrariesOptions({ query: { media_type: "movie" } }));
  const shows = createQuery(() => getLibrariesOptions({ query: { media_type: "show" } }));
  const catalog = new CatalogBrowsing();

  // Navigation starts before a lazy route finishes loading and changes pathname.
  $effect(() =>
    blockNavigation(() => {
      leaving = true;
      return true;
    }),
  );

  $effect(() => {
    if (leaving || !settings.isSuccess || !movies.isSuccess || !shows.isSuccess) return;
    const standalone = settings.data.media_server === null;
    if (standalone && !catalog.settled) return;
    // Without a media server the library holds only TMDB titles; the catalog is the start.
    const destination =
      standalone && catalog.browsable
        ? "/overturedb/movies"
        : movies.data.length === 0 && shows.data.length > 0
          ? "/shows"
          : "/movies";
    untrack(() => {
      void navigate(destination, { replace: true });
    });
  });
</script>

<DataStatus
  label="libraries"
  error={settings.error ?? movies.error ?? shows.error}
  loading={settings.isFetching || movies.isFetching || shows.isFetching}
  hasData={settings.isSuccess && movies.isSuccess && shows.isSuccess}
  onretry={() => {
    void settings.refetch();
    void movies.refetch();
    void shows.refetch();
  }}
/>
