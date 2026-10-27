<script lang="ts">
  import { onMount } from "svelte";
  import { MediaQuery } from "svelte/reactivity";
  import { session } from "./lib/auth/session.svelte";
  import AppLoader from "./lib/components/AppLoader.svelte";
  import Notice from "./lib/components/Notice.svelte";
  import NotificationHost from "./lib/components/NotificationHost.svelte";
  import PinnedNotices from "./lib/components/PinnedNotices.svelte";
  import ProductBrand from "./lib/components/ProductBrand.svelte";
  import { applyStoredAppearance, DARK_QUERY } from "./lib/utils/appearance";
  import { delayedFlag } from "./lib/utils/delayedFlag.svelte";
  import Login from "./Login.svelte";
  import Main from "./Main.svelte";

  let online = $state(true);
  // A connection blip that recovers at once never surfaces a notice.
  const showOffline = delayedFlag(() => !online);

  function updateConnection() {
    online = navigator.onLine;
    if (online && session.phase === "unavailable") void session.check();
  }

  // The "system" theme follows the device as it switches between light and dark.
  const systemDark = new MediaQuery(DARK_QUERY);
  $effect(() => {
    void systemDark.current;
    applyStoredAppearance();
  });

  onMount(() => {
    updateConnection();
    return session.start();
  });
</script>

<svelte:window ononline={updateConnection} onoffline={updateConnection} />

{#if session.phase === "checking" || session.phase === "logging-out"}
  <AppLoader />
{:else if session.phase === "unavailable"}
  <main class="unavailable-page">
    <div class="panel unavailable-card">
      <ProductBrand as="h1" size="lg" />
      <h2>Unable to connect</h2>
      <p role="alert">{session.error}</p>
      <button type="button" class="btn btn-primary" onclick={() => session.check()}
        >Retry connection</button
      >
    </div>
  </main>
{:else if session.phase === "authenticated"}
  <Main onLogout={() => void session.logout()} />
{:else}
  <Login onLogin={() => session.signedIn()} />
{/if}

<PinnedNotices>
  {#if showOffline.current}
    <Notice
      tone="warning"
      title="You're offline"
      message="Overture will reconnect when the server is available."
    />
  {/if}
</PinnedNotices>

<NotificationHost />

<style>
  .unavailable-page {
    display: grid;
    place-items: center;
    min-height: 100dvh;
    padding: var(--space-5);
  }

  .unavailable-card {
    display: grid;
    gap: var(--space-5);
    max-width: 460px;
    padding: var(--space-8);
    text-align: center;
  }

  .unavailable-card p {
    overflow-wrap: anywhere;
    color: var(--text-secondary);
  }
</style>
