<script lang="ts">
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import { createMutation } from "@tanstack/svelte-query";
  import { onMount } from "svelte";
  import { loginMutation } from "./generated/rest/@tanstack/svelte-query.gen";
  import { consumeLoginError } from "./lib/auth/loginError";
  import { loginRoute } from "./lib/auth/loginRoute";
  import { session } from "./lib/auth/session.svelte";
  import ProductBrand from "./lib/components/ProductBrand.svelte";
  import { isApiError } from "./lib/rest/transport";
  import { oidcLoginUrl } from "./lib/rest/urls";
  import { errorMessage } from "./lib/utils/errors";

  let { onLogin }: { onLogin: () => void } = $props();

  let password = $state("");
  let error = $state(consumeLoginError());
  const { returnTo, bypass, path } = loginRoute(window.location.href);
  const oidcHref = oidcLoginUrl(returnTo);
  onMount(() => {
    window.history.replaceState(null, "", path);
    if (
      (session.config.auth_mode === "oidc" || session.config.auth_mode === "both") &&
      session.config.auto_login &&
      !bypass &&
      !error
    ) {
      window.location.replace(oidcHref);
    }
  });
  let loading = $state(false);
  const loginRequest = createMutation(() => loginMutation());

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (loading) return;
    error = "";
    loading = true;
    try {
      await loginRequest.mutateAsync({ body: { password } });
      window.history.replaceState(null, "", returnTo);
      onLogin();
    } catch (err) {
      const msg = errorMessage(err, "");
      if (isApiError(err) && err.status === 401) {
        error = "Invalid credentials";
      } else if (isApiError(err) && err.status === 429) {
        error = "Too many attempts. Please wait a moment and try again.";
      } else {
        error = msg || "Login failed";
      }
    } finally {
      loading = false;
    }
  }
</script>

<div class="login-page">
  <div class="login-ambient"></div>
  <div class="login-card panel">
    <div class="login-header">
      <ProductBrand as="h1" size="lg" />
      <p class="login-subtitle">Artwork and theme manager</p>
    </div>

    {#if error}
      <div class="login-error" role="alert">{error}</div>
    {/if}

    {#if session.config.auth_mode === "oidc"}
      <a class="btn btn-primary login-btn" href={oidcHref}>
        {session.config.display_name}
      </a>
    {:else if session.config.auth_mode === "both" || session.config.auth_mode === "password"}
      <form class="login-form" onsubmit={handleSubmit}>
        <div class="form-group">
          <label class="form-label" for="login-password">Password</label>
          <input
            id="login-password"
            type="password"
            bind:value={password}
            placeholder="Enter password"
            autocomplete="current-password"
            required
          />
        </div>

        <button type="submit" class="btn btn-primary login-btn" disabled={loading || !password}>
          {#if loading}
            <LoaderCircle size={16} class="animate-spin" />
            Signing in...
          {:else}
            Sign In
          {/if}
        </button>
      </form>

      {#if session.config.auth_mode === "both"}
        <a class="btn btn-primary login-btn" href={oidcHref}>
          {session.config.display_name}
        </a>
      {/if}
    {/if}
  </div>
</div>

<style>
  .login-page {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100vh;
    height: 100dvh;
    min-height: 100svh;
    padding: calc(var(--space-4) + var(--safe-area-top))
      calc(var(--space-4) + var(--safe-area-right)) calc(var(--space-4) + var(--safe-area-bottom))
      calc(var(--space-4) + var(--safe-area-left));
    position: relative;
    overflow: hidden;
  }

  .login-ambient {
    position: absolute;
    inset: 0;
    background:
      radial-gradient(
        ellipse 60% 50% at 20% 30%,
        oklch(from var(--accent) l c h / 0.08) 0%,
        transparent 60%
      ),
      radial-gradient(
        ellipse 50% 60% at 80% 70%,
        oklch(from var(--accent) l c h / 0.06) 0%,
        transparent 60%
      );
    pointer-events: none;
  }

  .login-card {
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
    width: min(400px, 100%);
    padding: var(--space-10);
    position: relative;
    z-index: 1;
  }

  .login-header {
    text-align: center;
    margin-bottom: var(--space-3);
  }

  .login-header :global(.product-brand) {
    margin-bottom: var(--space-2);
  }

  .login-subtitle {
    color: var(--text-tertiary);
    font-size: var(--text-sm);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  .login-form {
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
  }

  .login-form input {
    width: 100%;
    padding: var(--space-3) var(--space-4);
  }

  .login-error {
    background: var(--danger-muted);
    color: var(--danger);
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius-sm);
    font-size: var(--text-sm);
    text-align: center;
  }

  .login-btn {
    width: 100%;
    padding: var(--space-3);
    font-size: var(--text-base);
    margin-top: var(--space-2);
  }

  @media (max-width: 480px) {
    .login-card {
      padding: var(--space-6);
    }

    .login-header {
      margin-bottom: var(--space-1);
    }
  }
</style>
