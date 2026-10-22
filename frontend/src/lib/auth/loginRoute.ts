import { LOGIN_PATH } from "../../generated/settings";

export type LoginRoute = {
  /** The app path to open once signed in. */
  returnTo: string;
  /** Whether the visitor opted out of the automatic SSO sign-in. */
  bypass: boolean;
  /** The login page URL that stands in for *href* while signed out. */
  path: string;
};

/** Resolve the signed-out visit to *href* into the login page and its return path. */
export function loginRoute(href: string): LoginRoute {
  const requested = new URL(href);
  const bypass = requested.searchParams.get("autologin") === "0";
  requested.searchParams.delete("autologin");
  // Resolving against this origin keeps a crafted return_to on this site.
  const returnUrl = new URL(
    requested.pathname === LOGIN_PATH
      ? (requested.searchParams.get("return_to") ?? "/")
      : requested.pathname + requested.search,
    requested.origin,
  );
  const returnTo = returnUrl.pathname + returnUrl.search;
  const query = new URLSearchParams();
  if (bypass) query.set("autologin", "0");
  if (returnTo !== "/") query.set("return_to", returnTo);
  const search = query.toString();
  return { returnTo, bypass, path: search ? `${LOGIN_PATH}?${search}` : LOGIN_PATH };
}
