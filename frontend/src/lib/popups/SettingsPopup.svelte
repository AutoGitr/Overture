<script lang="ts">
  import { createMutation, createQuery, useQueryClient } from "@tanstack/svelte-query";
  import { invalidateTags } from "../rest/cache";
  import {
    getSettingsOptions,
    updateSettingsMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { DEFAULT_APP_SETTINGS } from "../../generated/settings";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import {
    applyAppearancePreferences,
    DEFAULT_APPEARANCE,
    loadAppearancePreferences,
    saveAppearancePreferences,
    withThemeMode,
    type AppearancePreferences,
  } from "../utils/appearance";
  import { delayedFlag } from "../utils/delayedFlag.svelte";
  import { errorMessage } from "../utils/errors";
  import CardColumn from "../components/CardColumn.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  import ColorInput from "../components/ColorInput.svelte";

  const queryClient = useQueryClient();

  const draft = $state(settingsState.toUpdatePayload());
  const settingsQuery = createQuery(() => getSettingsOptions());
  let draftInitialised = $state(false);
  let canEdit = $derived(draftInitialised && !settingsQuery.isError);
  $effect(() => {
    if (settingsQuery.data && !draftInitialised) {
      Object.assign(draft, settingsState.toUpdatePayload());
      draftInitialised = true;
    }
  });
  let saving = $state(false);
  const showSaving = delayedFlag(() => saving);
  const feedback = createNotifier();
  const updateSettingsRequest = createMutation(() => updateSettingsMutation());

  let appearance = $state<AppearancePreferences>({
    ...loadAppearancePreferences(),
    showBackgroundImage: settingsState.show_background_image,
  });

  async function save() {
    if (saving || !canEdit) return;
    saving = true;
    feedback.clear();
    try {
      const previousTolerance = settingsState.current.aspect_ratio_tolerance;
      const fresh = await updateSettingsRequest.mutateAsync({ body: draft });
      queryClient.setQueryData(getSettingsOptions().queryKey, fresh);
      // Library items carry has_incorrect_aspect_ratio, computed for the tolerance.
      await invalidateTags(
        settingsState.current.aspect_ratio_tolerance === previousTolerance
          ? ["art"]
          : ["art", "library"],
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
      <div class="option-card">
        <span class="form-label">Artwork</span>
        <div class="options-col">
          <label class="form-row justify-between">
            <span>Aspect ratio control</span>
            <select bind:value={draft.aspect_ratio_tolerance} class="select-compact">
              <option value="strict">Strict (+/-1%)</option>
              <option value="lenient">Lenient (+/-5%)</option>
              <option value="off">Off (any ratio)</option>
            </select>
          </label>
          <label class="form-row justify-between">
            <span>Auto-Match Art on Load</span>
            <input type="checkbox" bind:checked={draft.auto_match_art} />
          </label>
          <label class="form-row justify-between">
            <span>
              Skip TMDB images from {settingsState.media_server_name}
            </span>
            <input type="checkbox" bind:checked={draft.skip_media_server_tmdb_urls} />
          </label>
          <label class="form-row justify-between">
            <span>
              Disable fetching art from {settingsState.media_server_name}
            </span>
            <input type="checkbox" bind:checked={draft.disable_media_server_art} />
          </label>
          {#if settingsState.current.tmdb_configured}
            <label class="form-row justify-between">
              <span>TMDB image languages</span>
              <select bind:value={draft.tmdb_language_filter} class="select-compact">
                <option value="en_null">English and undefined only</option>
                <option value="all">All languages</option>
              </select>
            </label>
          {/if}
        </div>
      </div>

      <div class="option-card">
        <span class="form-label">Themes</span>
        <div class="options-col">
          <div class="form-row">
            <label for="theme-search-format">Theme Search Query</label>
            <input
              id="theme-search-format"
              type="text"
              class="text-input"
              aria-describedby="theme-search-variables"
              bind:value={draft.theme_search_format}
              placeholder={DEFAULT_APP_SETTINGS.theme_search_format}
            />
          </div>
          <span class="hint" id="theme-search-variables">
            Variables: <code>{"{title}"}</code> <code>{"{year}"}</code>
          </span>
          <div class="duration-range">
            <div class="duration-field">
              <label for="min-theme-duration">Min Theme Duration (seconds)</label>
              <input
                id="min-theme-duration"
                type="number"
                class="number-input"
                min="0"
                bind:value={draft.min_duration_seconds}
              />
            </div>
            <div class="duration-field">
              <label for="max-theme-duration">Max Theme Duration (seconds)</label>
              <input
                id="max-theme-duration"
                type="number"
                class="number-input"
                min="0"
                bind:value={draft.max_duration_seconds}
              />
            </div>
          </div>
          <label class="form-row justify-between">
            <span>Normalize theme loudness</span>
            <input type="checkbox" bind:checked={draft.normalize_theme_loudness} />
          </label>
        </div>
      </div>

      <div class="option-card">
        <span class="form-label">Workflow</span>
        <div class="options-col">
          <label class="form-row justify-between">
            <span>Workflow</span>
            <select bind:value={draft.workflow} class="select-compact">
              <option value="art">Art</option>
              <option value="art_and_themes">Art + themes</option>
              <option value="themes">Themes</option>
            </select>
          </label>
          <label class="form-row justify-between">
            <span>Auto-advance</span>
            <input type="checkbox" bind:checked={draft.auto_advance} />
          </label>
          <label class="form-row justify-between">
            <span>Skip completed slots and items</span>
            <input
              type="checkbox"
              bind:checked={draft.auto_advance_skip_completed}
              disabled={!draft.auto_advance}
            />
          </label>
          <label class="form-row justify-between">
            <span>Auto-unmonitor</span>
            <select bind:value={draft.auto_unmonitor} class="select-compact">
              <option value="off">Off</option>
              <option value="art">Art complete</option>
              <option value="theme">Theme complete</option>
              <option value="art_or_theme">Art or theme complete</option>
              <option value="art_and_theme">Art and theme complete</option>
            </select>
          </label>
          {#if settingsState.current.media_server === "plex"}
            <label class="form-row justify-between">
              <span>Enable Collections</span>
              <input type="checkbox" bind:checked={draft.plex_collections_enabled} />
            </label>
          {/if}
        </div>
      </div>

      <div class="option-card">
        <span class="form-label">Appearance</span>
        <div class="options-col">
          <label class="form-row justify-between">
            <span>Theme Mode</span>
            <select
              class="select-compact"
              value={appearance.theme}
              onchange={(event) =>
                (appearance = withThemeMode(
                  appearance,
                  event.currentTarget.value === "light" ? "light" : "dark",
                ))}
            >
              <option value="dark">Dark</option>
              <option value="light">Light</option>
            </select>
          </label>
          <div class="form-row justify-between">
            <label for="accent-color">Accent Color</label>
            <ColorInput
              id="accent-color"
              label="Accent Color"
              bind:value={appearance.accentColor}
              disabled={!canEdit || showSaving.current}
            />
          </div>
          <div class="form-row justify-between">
            <label for="bg-color">Background Color</label>
            <ColorInput
              id="bg-color"
              label="Background Color"
              bind:value={appearance.bgColor}
              disabled={!canEdit || showSaving.current}
            />
          </div>
          <label class="form-row justify-between">
            <span>Show Background Image</span>
            <input type="checkbox" bind:checked={appearance.showBackgroundImage} />
          </label>
          <button
            class="btn btn-ghost btn-sm self-start reset-defaults-btn"
            onclick={() => (appearance = { ...DEFAULT_APPEARANCE })}>Reset Defaults</button
          >
        </div>
      </div>
    </CardColumn>
  </fieldset>
  {#snippet footer()}
    <button class="btn btn-ghost" onclick={() => uiState.closePopup()}>Cancel</button>
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

  .reset-defaults-btn {
    margin-left: -8px;
  }

  .duration-range {
    display: flex;
    flex-flow: row wrap;
    gap: var(--space-2) var(--space-6);
  }
  .duration-field {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }
</style>
