<script lang="ts">
  import fanartIcon from "../../assets/icons/fanart.svg";
  import imdbIcon from "../../assets/icons/imdb.svg";
  import letterboxdIcon from "../../assets/icons/letterboxd.svg";
  import tmdbIcon from "../../assets/icons/tmdb.svg";
  import tpdbIcon from "../../assets/icons/tpdb.svg";
  import tvdbIcon from "../../assets/icons/tvdb.svg";
  import youtubeIcon from "../../assets/icons/youtube.svg";
  import type { ArtType } from "../../generated/rest/types.gen";
  import { settingsState } from "../stores/settingsState.svelte";
  import {
    type DetailSubject,
    buildFanartUrl,
    buildImdbUrl,
    buildLetterboxdUrl,
    buildPosterDbUrl,
    buildTmdbUrl,
    buildTvdbUrl,
  } from "../utils/externalLinks";
  import {
    buildCollectionThemeSearchQuery,
    buildThemeSearchQuery,
    youtubeSearchUrl,
  } from "../utils/themeSearch";
  import IdBadge from "./IdBadge.svelte";

  /**
   * Links to the subject on the sites its identifiers name, and to where the
   * open section's art or theme can be searched for.
   */
  let {
    subject,
    mode,
    artType,
    season,
  }: {
    subject: DetailSubject | null;
    mode: string;
    artType: ArtType;
    /** The season drilled into, whose page the TMDB link opens. */
    season: { season_num: number } | null;
  } = $props();

  let tmdbUrl = $derived(buildTmdbUrl(subject, mode, artType, season));
  let tvdbUrl = $derived(buildTvdbUrl(subject));
  let letterboxdUrl = $derived(buildLetterboxdUrl(subject));
  let youtubeUrl = $derived(
    subject && mode === "themes"
      ? youtubeSearchUrl(
          subject.media_type === "collection"
            ? buildCollectionThemeSearchQuery(subject.title)
            : buildThemeSearchQuery(subject, settingsState.current.theme_search_format),
        )
      : null,
  );
  let posterDbUrl = $derived(mode === "art" ? buildPosterDbUrl(subject) : null);
  let fanartUrl = $derived(mode === "art" ? buildFanartUrl(subject, mode, artType) : null);
</script>

{#if tmdbUrl}
  <IdBadge href={tmdbUrl} title="The Movie Database" icon={tmdbIcon} alt="TMDb" />
{/if}
{#if tvdbUrl}
  <IdBadge href={tvdbUrl} title="TheTVDB" icon={tvdbIcon} alt="TVDB" />
{/if}
{#if subject?.imdb_id}
  <IdBadge href={buildImdbUrl(subject.imdb_id)} title="IMDb" icon={imdbIcon} alt="IMDb" />
{/if}
{#if letterboxdUrl}
  <IdBadge href={letterboxdUrl} title="Letterboxd" icon={letterboxdIcon} alt="Letterboxd" />
{/if}
{#if youtubeUrl}
  <IdBadge href={youtubeUrl} title="Search YouTube" icon={youtubeIcon} alt="YouTube" />
{/if}
{#if posterDbUrl}
  <IdBadge href={posterDbUrl} title="The Poster Database" icon={tpdbIcon} alt="TPDb" />
{/if}
{#if fanartUrl}
  <IdBadge href={fanartUrl} title="Fanart.tv" icon={fanartIcon} alt="Fanart" />
{/if}
