const messages: Record<string, string> = {
  oidc_denied: "Sign-in was denied by your identity provider.",
  oidc_expired: "Your sign-in attempt expired. Please start again.",
  oidc_unavailable: "Your sign-in provider is unavailable. Please try again shortly.",
  oidc_invalid: "Could not verify your sign-in. Please start again.",
};

export function consumeLoginError(): string {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("auth_error");
  if (!code) return "";
  url.searchParams.delete("auth_error");
  window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
  return messages[code] ?? "Could not sign in. Please try again.";
}
