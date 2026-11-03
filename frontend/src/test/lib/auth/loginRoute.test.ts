import { describe, expect, it } from "vitest";
import { loginRoute } from "../../../lib/auth/loginRoute";

const origin = "https://overture.example.test";

describe("loginRoute", () => {
  it.each([
    ["/", { returnTo: "/", bypass: false, path: "/login" }],
    ["/?autologin=0", { returnTo: "/", bypass: true, path: "/login?autologin=0" }],
    [
      "/shows/42-example/art?season=1",
      {
        returnTo: "/shows/42-example/art?season=1",
        bypass: false,
        path: "/login?return_to=%2Fshows%2F42-example%2Fart%3Fseason%3D1",
      },
    ],
    [
      "/login?autologin=0&return_to=%2Fmovies",
      { returnTo: "/movies", bypass: true, path: "/login?autologin=0&return_to=%2Fmovies" },
    ],
  ])("resolves %s", (path, expected) => {
    expect(loginRoute(origin + path)).toEqual(expected);
  });

  it.each(["//evil.example/movies", "https://evil.example/movies"])(
    "keeps the crafted return_to %s on this origin",
    (target) => {
      const href = `${origin}/login?return_to=${encodeURIComponent(target)}`;
      expect(loginRoute(href).returnTo).toBe("/movies");
    },
  );
});
