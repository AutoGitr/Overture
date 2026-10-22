import { client } from "../../generated/rest/client.gen";
import type {
  OidcLoginData,
  ProxyItemProviderArtData,
  ProxySeasonProviderArtData,
  ServeLocalImageData,
  ServeLocalSeasonImageData,
} from "../../generated/rest/types.gen";

/**
 * URLs of endpoints the browser loads itself, as an image source or a
 * redirect, rather than through a request. Each is built from its generated
 * request type, so a renamed route or parameter fails the type check instead
 * of a page; they stay same-origin paths, like every request.
 */
const SAME_ORIGIN = { baseUrl: "" } as const;

export function localItemImageUrl(
  path: ServeLocalImageData["path"],
  query: ServeLocalImageData["query"],
): string {
  return client.buildUrl<ServeLocalImageData>({
    ...SAME_ORIGIN,
    url: "/api/library/items/{item_id}/local-image/{art_type}",
    path,
    query,
  });
}

export function itemProviderArtUrl(
  path: ProxyItemProviderArtData["path"],
  query: ProxyItemProviderArtData["query"],
): string {
  return client.buildUrl<ProxyItemProviderArtData>({
    ...SAME_ORIGIN,
    url: "/api/library/items/{item_id}/provider-art",
    path,
    query,
  });
}

export function localSeasonImageUrl(
  path: ServeLocalSeasonImageData["path"],
  query: ServeLocalSeasonImageData["query"],
): string {
  return client.buildUrl<ServeLocalSeasonImageData>({
    ...SAME_ORIGIN,
    url: "/api/library/seasons/{season_id}/local-image",
    path,
    query,
  });
}

export function seasonProviderArtUrl(
  path: ProxySeasonProviderArtData["path"],
  query: ProxySeasonProviderArtData["query"],
): string {
  return client.buildUrl<ProxySeasonProviderArtData>({
    ...SAME_ORIGIN,
    url: "/api/library/seasons/{season_id}/provider-art",
    path,
    query,
  });
}

/** Where the OIDC sign-in starts, returning to *returnTo* once signed in. */
export function oidcLoginUrl(returnTo: string): string {
  return client.buildUrl<OidcLoginData>({
    ...SAME_ORIGIN,
    url: "/api/auth/oidc/login",
    query: { return_to: returnTo },
  });
}
