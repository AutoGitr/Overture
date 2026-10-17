<script lang="ts">
  import { onMount } from "svelte";
  import { session } from "./lib/auth/session.svelte";
  import AppLoader from "./lib/components/AppLoader.svelte";
  import Notice from "./lib/components/Notice.svelte";
  import NotificationHost from "./lib/components/NotificationHost.svelte";
  import PinnedNotices from "./lib/components/PinnedNotices.svelte";
  import ProductBrand from "./lib/components/ProductBrand.svelte";
  import { applyStoredAppearance } from "./lib/utils/appearance";
  import { delayedFlag } from "./lib/utils/delayedFlag.svelte";
  import Login from "./Login.svelte";
  import Main from "./Main.svelte";

  let startupReady = $state(false);
  let online = $state(true);
  // A connection blip that recovers at once never surfaces a notice.
  const showOffline = delayedFlag(() => !online);

  $effect(() => {
    if (session.phase !== "authenticated") startupReady = false;
  });

  onMount(() => {
    const updateConnection = () => {
      online = navigator.onLine;
      if (online && session.phase === "unavailable") void session.check();
    };

    updateConnection();
    const stopSession = session.start();
    applyStoredAppearance();

    window.addEventListener("online", updateConnection);
    window.addEventListener("offline", updateConnection);
    return () => {
      stopSession();
      window.removeEventListener("online", updateConnection);
      window.removeEventListener("offline", updateConnection);
    };
  });
</script>

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
  <Main onLogout={() => void session.logout()} onReady={() => (startupReady = true)} />
  {#if !startupReady}
    <div class="startup-overlay">
      <AppLoader />
    </div>
  {/if}
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

  .startup-overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
  }
</style>
