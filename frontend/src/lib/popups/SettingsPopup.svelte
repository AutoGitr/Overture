<script lang="ts">
  import { createMutation, createQuery, useQueryClient } from "@tanstack/svelte-query";
  import { invalidateTags } from "../rest/cache";
  import {
    getCatalogStatusOptions,
    getSettingsOptions,
    setCatalogEnabledMutation,
    updateSettingsMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { ASPECT_TOLERANCES, DEFAULT_APP_SETTINGS } from "../../generated/settings";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { SectionView, setSectionView } from "../stores/sectionState.svelte";
  import { catalogSyncState } from "../stores/jobStates.svelte";
  import { settingsState, type SettingsDraft } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import {
    applyAppearancePreferences,
    DEFAULT_APPEARANCE,
    loadAppearancePreferences,
    saveAppearancePreferences,
    type AppearancePreferences,
    type ThemeMode,
  } from "../utils/appearance";
  import { delayedFlag } from "../utils/delayedFlag.svelte";
  import { draftOf } from "../utils/draft.svelte";
  import { errorMessage } from "../utils/errors";
  import CardColumn from "../components/CardColumn.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  import ColorInput from "../components/ColorInput.svelte";
  import GlobalCollectionDefaults from "../components/GlobalCollectionDefaults.svelte";
  import OvertureDbSettings from "../components/OvertureDbSettings.svelte";
  import PopupSection from "../components/PopupSection.svelte";
  import SegmentedControl from "../components/SegmentedControl.svelte";
  import Select from "../components/Select.svelte";
  import type { SelectOption } from "../utils/selectOptions";

  const THEMES: readonly (readonly [ThemeMode, string])[] = [
    ["system", "System"],
    ["light", "Light"],
    ["dark", "Dark"],
  ];

  const AUTO_ADVANCE: readonly (readonly [SettingsDraft["auto_advance"], string])[] = [
    ["off", "Off"],
    ["slots", "Slots"],
    ["slots_and_items", "Slots and items"],
  ];
  const WORKFLOWS: SelectOption<SettingsDraft["workflow"]>[] = [
    { value: "art", label: "Art" },
    { value: "art_and_themes", label: "Art & Themes" },
    { value: "themes", label: "Themes" },
  ];
  const AUTO_UNMONITOR: SelectOption<SettingsDraft["auto_unmonitor"]>[] = [
    { value: "off", label: "Off" },
    { value: "art", label: "Art complete" },
    { value: "theme", label: "Theme complete" },
    { value: "art_or_theme", label: "Art or theme complete" },
    { value: "art_and_theme", label: "Art and theme complete" },
  ];
  const ASPECT_TOLERANCE_OPTIONS: SelectOption<SettingsDraft["aspect_ratio_tolerance"]>[] = [
    { value: "strict", label: `Strict (+/-${percent(ASPECT_TOLERANCES.strict)})` },
    { value: "lenient", label: `Lenient (+/-${percent(ASPECT_TOLERANCES.lenient)})` },
    { value: "off", label: "Off (any ratio)" },
  ];
  const TMDB_LANGUAGES: SelectOption<SettingsDraft["tmdb_language_filter"]>[] = [
    { value: "en_null", label: "English and undefined only" },
    { value: "all", label: "All languages" },
  ];

  // Its sections stay as the user left them across visits and reloads.
  setSectionView(new SectionView(() => true, "settings"));
  const id = $props.id();
  const queryClient = useQueryClient();

  const settingsQuery = createQuery(() => getSettingsOptions());
  /** Every editable setting, taken once they load; the settings store follows the query. */
  const draft = draftOf(
    () => settingsQuery.data && settingsState.toUpdatePayload(),
    settingsState.toUpdatePayload(),
  );
  let canEdit = $derived(settingsQuery.data !== undefined && !settingsQuery.isError);
  let saving = $state(false);
  const showSaving = delayedFlag(() => saving);
  const feedback = createNotifier();
  const updateSettingsRequest = createMutation(() => updateSettingsMutation());
  const catalogQuery = createQuery(() => getCatalogStatusOptions());
  const saveCatalogEnabledRequest = createMutation(() => setCatalogEnabledMutation());
  /** The OvertureDB switch, which its schedule holds rather than the app settings. */
  let catalogEnabled = $derived(catalogQuery.data?.enabled ?? false);
  let catalogEnabledDirty = $derived(catalogEnabled !== (catalogQuery.data?.enabled ?? false));

  let appearance = $state<AppearancePreferences>({
    ...loadAppearancePreferences(),
    showBackgroundImage: settingsState.show_background_image,
  });

  async function save() {
    if (saving || !canEdit) return;
    saving = true;
    feedback.clear();
    try {
      const previous = settingsState.current;
      const fresh = await updateSettingsRequest.mutateAsync({ body: draft.current });
      queryClient.setQueryData(getSettingsOptions().queryKey, fresh);
      if (catalogEnabledDirty) {
        const status = await saveCatalogEnabledRequest.mutateAsync({
          body: { enabled: catalogEnabled },
        });
        queryClient.setQueryData(getCatalogStatusOptions().queryKey, status);
      }
      // Refetch in the background: art candidates come from remote sources, and
      // waiting for them made saving slow. Library items carry
      // has_incorrect_aspect_ratio, computed for the tolerance, and their theme
      // completeness, which follows OvertureDB's No theme flag.
      void invalidateTags(
        previous.aspect_ratio_tolerance === draft.current.aspect_ratio_tolerance &&
          previous.overturedb_no_theme === draft.current.overturedb_no_theme
          ? ["art", "collections"]
          : ["art", "library", "collections"],
      );
      saveAppearancePreferences(appearance);
      settingsState.show_background_image = appearance.showBackgroundImage;
      applyAppearancePreferences(appearance);
      uiState.closePopup();
      feedback.success("Settings saved.");
    } catch (err) {
      feedback.error(errorMessage(err, "Failed to save settings"));
    }
    saving = false;
  }

  /** Put every setting back to its default in the form; only Save keeps it. */
  function resetToDefaults() {
    for (const key of Object.keys(draft.current) as (keyof typeof draft.current)[]) {
      if (key in DEFAULT_APP_SETTINGS)
        Object.assign(draft.current, { [key]: DEFAULT_APP_SETTINGS[key as keyof typeof DEFAULT_APP_SETTINGS] });
    }
    appearance = { ...DEFAULT_APPEARANCE };
  }

  function percent(fraction: number): string {
    return `${Number((fraction * 100).toFixed(1))}%`;
  }
</script>

<PopupShell title="Settings" onclose={() => uiState.closePopup()}>
  <DataStatus
    label="settings"
    error={settingsQuery.error}
    loading={settingsQuery.isFetching}
    hasData={settingsQuery.data !== undefined}
    onretry={() => settingsQuery.refetch()}
  />
  <fieldset
    class="settings-fields"
    disabled={!canEdit || showSaving.current}
    inert={saving}
    aria-label="Application settings"
  >
    <CardColumn>
      <PopupSection label="Workflow">
        <div class="options-col">
          <div class="form-row justify-between">
            <label for={`${id}-workflow`}>Workflow</label>
            <Select
              id={`${id}-workflow`}
              compact
              options={WORKFLOWS}
              bind:value={draft.current.workflow}
            />
          </div>
          <label class="form-row justify-between">
            <span>Auto-match art on load</span>
            <input type="checkbox" bind:checked={draft.current.auto_match_art} />
          </label>
          <label class="form-row justify-between">
            <span>Auto-search themes on load</span>
            <input type="checkbox" bind:checked={draft.current.auto_search_themes} />
          </label>
          <div class="form-row justify-between">
            <span>Auto-advance</span>
            <SegmentedControl
              --segmented-width="auto"
              --segmented-margin="0"
              label="Auto-advance"
              options={AUTO_ADVANCE}
              bind:value={draft.current.auto_advance}
            />
          </div>
          <span class="hint"
            >After a selection, open the next slot, and with Slots and items the next item. The
            Themes workflow has one slot, so there Slots behaves like Off.</span
          >
          <label class="form-row justify-between">
            <span>Skip completed slots and items</span>
            <input
              type="checkbox"
              bind:checked={draft.current.auto_advance_skip_completed}
              disabled={draft.current.auto_advance === "off"}
            />
          </label>
          <div class="form-row justify-between">
            <label for={`${id}-unmonitor`}>Auto-unmonitor</label>
            <Select
              id={`${id}-unmonitor`}
              compact
              options={AUTO_UNMONITOR}
              bind:value={draft.current.auto_unmonitor}
            />
          </div>
        </div>
      </PopupSection>

      <PopupSection label="Artwork">
        <div class="options-col">
          <div class="form-row justify-between">
            <label for={`${id}-aspect`}>Aspect ratio control</label>
            <Select
              id={`${id}-aspect`}
              compact
              options={ASPECT_TOLERANCE_OPTIONS}
              bind:value={draft.current.aspect_ratio_tolerance}
            />
          </div>
          <label class="form-row justify-between">
            <span>
              Skip TMDB images from {settingsState.media_server_name}
            </span>
            <input type="checkbox" bind:checked={draft.current.skip_media_server_tmdb_urls} />
          </label>
          <label class="form-row justify-between">
            <span>
              Disable fetching art from {settingsState.media_server_name}
            </span>
            <input type="checkbox" bind:checked={draft.current.disable_media_server_art} />
          </label>
          {#if settingsState.current.tmdb_configured}
            <div class="form-row justify-between">
              <label for={`${id}-tmdb-lang`}>TMDB image languages</label>
              <Select
                id={`${id}-tmdb-lang`}
                compact
                options={TMDB_LANGUAGES}
                bind:value={draft.current.tmdb_language_filter}
              />
            </div>
          {/if}
        </div>
      </PopupSection>

      <PopupSection label="Themes">
        <div class="options-col">
          <div class="form-row">
            <label for="theme-search-format">Theme search query</label>
            <input
              id="theme-search-format"
              type="text"
              class="text-input"
              aria-describedby="theme-search-variables"
              bind:value={draft.current.theme_search_format}
              placeholder={DEFAULT_APP_SETTINGS.theme_search_format}
            />
          </div>
          <span class="hint" id="theme-search-variables">
            Variables: <code>{"{title}"}</code> <code>{"{year}"}</code>
          </span>
          <div class="duration-range">
            <div class="duration-field">
              <label for="min-theme-duration">Shortest theme (seconds)</label>
              <input
                id="min-theme-duration"
                type="number"
                class="number-input"
                min="0"
                bind:value={draft.current.min_duration_seconds}
              />
            </div>
            <div class="duration-field">
              <label for="max-theme-duration">Longest theme (seconds)</label>
              <input
                id="max-theme-duration"
                type="number"
                class="number-input"
                min="0"
                bind:value={draft.current.max_duration_seconds}
              />
            </div>
          </div>
          <label class="form-row justify-between">
            <span>Normalize theme loudness</span>
            <input type="checkbox" bind:checked={draft.current.normalize_theme_loudness} />
          </label>
        </div>
      </PopupSection>

      <PopupSection label="Collections">
        <GlobalCollectionDefaults bind:draft={draft.current} />
      </PopupSection>

      <PopupSection label="OvertureDB">
        <DataStatus
          label="OvertureDB status"
          error={catalogQuery.error}
          loading={catalogQuery.isFetching}
          hasData={catalogQuery.data !== undefined}
          onretry={() => catalogQuery.refetch()}
        />
        {#if catalogQuery.data}
          <OvertureDbSettings
            bind:draft={draft.current}
            bind:enabled={catalogEnabled}
            disabled={catalogSyncState.running}
          />
        {/if}
      </PopupSection>

      <PopupSection label="Appearance">
        <div class="options-col">
          <div class="form-row justify-between">
            <span>Theme</span>
            <SegmentedControl
              --segmented-width="auto"
              --segmented-margin="0"
              label="Theme"
              options={THEMES}
              bind:value={appearance.theme}
            />
          </div>
          <label class="form-row justify-between">
            <span>Increase contrast</span>
            <input
              type="checkbox"
              checked={appearance.contrast === "more"}
              onchange={(event) =>
                (appearance.contrast = event.currentTarget.checked ? "more" : "standard")}
            />
          </label>
          <div class="form-row justify-between">
            <label for="accent-color">Accent color</label>
            <ColorInput
              id="accent-color"
              label="Accent color"
              bind:value={appearance.accentColor}
              disabled={!canEdit || showSaving.current}
            />
          </div>
          <label class="form-row justify-between">
            <span>Show background image</span>
            <input type="checkbox" bind:checked={appearance.showBackgroundImage} />
          </label>
        </div>
      </PopupSection>

    </CardColumn>
  </fieldset>
  {#snippet footer()}
    <button
      type="button"
      class="btn btn-secondary actions-start"
      onclick={resetToDefaults}
      disabled={showSaving.current || !canEdit}>Reset to defaults</button
    >
    <button class="btn btn-secondary" onclick={() => uiState.closePopup()}>Cancel</button>
    <button class="btn btn-primary" onclick={save} disabled={showSaving.current || !canEdit}>
      {showSaving.current ? "Saving..." : "Save"}
    </button>
  {/snippet}
</PopupShell>

<style>
  .settings-fields {
    border: 0;
    margin: 0;
    padding: 0;
    min-width: 0;
  }

  .duration-range {
    display: flex;
    flex-flow: row wrap;
    gap: var(--space-2) var(--space-6);
  }
  .duration-field {
    flex: 1 1 16rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }
</style>
