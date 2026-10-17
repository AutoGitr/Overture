<script lang="ts">
  import fanartIcon from "../../assets/icons/fanart.svg";
  import imdbIcon from "../../assets/icons/imdb.svg";
  import letterboxdIcon from "../../assets/icons/letterboxd.svg";
  import tmdbIcon from "../../assets/icons/tmdb.svg";
  import tpdbIcon from "../../assets/icons/tpdb.svg";
  import tvdbIcon from "../../assets/icons/tvdb.svg";
  import youtubeIcon from "../../assets/icons/youtube.svg";
  import type { ArtType } from "../../generated/rest/types.gen";
  import type { DetailSubject } from "../stores/selectedState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import {
    buildFanartUrl,
    buildImdbUrl,
    buildLetterboxdUrl,
    buildPosterDbUrl,
    buildTmdbUrl,
    buildTvdbUrl,
  } from "../utils/externalLinks";
  import { buildThemeSearchQuery, youtubeSearchUrl } from "../utils/themeSearch";

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
      ? youtubeSearchUrl(buildThemeSearchQuery(subject, settingsState.current.theme_search_format))
      : null,
  );
  let posterDbUrl = $derived(mode === "art" ? buildPosterDbUrl(subject) : null);
  let fanartUrl = $derived(mode === "art" ? buildFanartUrl(subject, mode, artType) : null);
</script>

{#if tmdbUrl}
  <a class="id-badge tmdb" href={tmdbUrl} target="_blank" rel="noopener" title="The Movie Database"
    ><img src={tmdbIcon} alt="TMDb" /></a
  >
{/if}
{#if tvdbUrl}
  <a class="id-badge tvdb" href={tvdbUrl} target="_blank" rel="noopener" title="TheTVDB"
    ><img src={tvdbIcon} alt="TVDB" /></a
  >
{/if}
{#if subject?.imdb_id}
  <a
    class="id-badge imdb"
    href={buildImdbUrl(subject.imdb_id)}
    target="_blank"
    rel="noopener"
    title="IMDb"><img src={imdbIcon} alt="IMDb" /></a
  >
{/if}
{#if letterboxdUrl}
  <a
    class="id-badge letterboxd"
    href={letterboxdUrl}
    target="_blank"
    rel="noopener"
    title="Letterboxd"><img src={letterboxdIcon} alt="Letterboxd" /></a
  >
{/if}
{#if youtubeUrl}
  <a
    class="id-badge youtube"
    href={youtubeUrl}
    target="_blank"
    rel="noopener"
    title="Search YouTube"><img src={youtubeIcon} alt="YouTube" /></a
  >
{/if}
{#if posterDbUrl}
  <a
    class="id-badge tpdb"
    href={posterDbUrl}
    target="_blank"
    rel="noopener noreferrer"
    title="The Poster Database"><img src={tpdbIcon} alt="TPDb" referrerpolicy="no-referrer" /></a
  >
{/if}
{#if fanartUrl}
  <a
    class="id-badge fanart"
    href={fanartUrl}
    target="_blank"
    rel="noopener noreferrer"
    title="Fanart.tv"
  >
    <img src={fanartIcon} alt="Fanart" referrerpolicy="no-referrer" /></a
  >
{/if}
