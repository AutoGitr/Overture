import { expect, test, type APIResponse, type Page } from "@playwright/test";

async function signIn(page: Page, path = "/shows/42-example/art") {
  await page.goto(path);
  await expect(page.getByLabel("Password")).toHaveCount(0);
  await page.getByRole("link", { name: "Sign in with SSO" }).click();
  await expect(page).toHaveURL(/^http:\/\/localhost:8697\/provider\/authorize\?/);
  await page.getByRole("link", { name: "Approve sign-in" }).click();
  await expect(page).toHaveURL(`http://127.0.0.1:8697${path}`);
}

async function authenticated(page: Page) {
  return page.evaluate(async () => {
    const response = await fetch("/api/auth/me");
    const body: { authenticated: boolean } = await response.json();
    return body.authenticated;
  });
}

test.beforeEach(async ({ request }) => {
  await request.get("/__test/reset");
});

test("cross-site sign-in preserves the deep link and enforces cookies, CSRF, and logout", async ({
  page,
  context,
}) => {
  await signIn(page);
  expect(await authenticated(page)).toBe(true);
  const cookies = await context.cookies();
  expect(cookies.find((cookie) => cookie.name === "overture_token")).toMatchObject({
    httpOnly: true,
    sameSite: "Strict",
  });
  expect(cookies.some((cookie) => cookie.name === "overture_oidc")).toBe(false);
  const results = await page.evaluate(async () => {
    const denied = await fetch("/api/auth/logout", { method: "POST" });
    const csrf =
      document.cookie
        .split("; ")
        .find((cookie) => cookie.startsWith("overture_csrf="))
        ?.split("=")[1] ?? "";
    const logout = await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "X-CSRF-Token": csrf },
    });
    return [denied.status, logout.status];
  });
  expect(results).toEqual([403, 200]);
  expect(await authenticated(page)).toBe(false);
  await page.reload();
  await expect(page.getByRole("link", { name: "Sign in with SSO" })).toBeVisible();
  expect(page.url()).not.toContain("/provider/");
});

test("invalid signed identity show a clean retry screen without establishing a session", async ({
  page,
  request,
}) => {
  await request.get("/__test/reset?scenario=denied");
  await page.goto("/");
  await page.getByRole("link", { name: "Sign in with SSO" }).click();
  await page.getByRole("link", { name: "Approve sign-in" }).click();
  await expect(page.getByRole("alert")).toContainText("Could not verify your sign-in");
  await expect(page).toHaveURL("http://127.0.0.1:8697/login?autologin=0");
  expect(await authenticated(page)).toBe(false);
  await request.get("/__test/reset");
  await signIn(page, "/movies");
  expect(await authenticated(page)).toBe(true);
});

test("installed service worker lets OIDC navigations reach the backend", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.reload();
  await expect
    .poll(() => page.evaluate(() => navigator.serviceWorker.controller !== null))
    .toBe(true);
  await signIn(page, "/movies");
  expect(await authenticated(page)).toBe(true);
});

test("an established WebSocket closes when the local session expires", async ({
  page,
  request,
}) => {
  await request.get("/__test/reset?scenario=expiry");
  await signIn(page, "/movies");
  const code = await page.evaluate(
    () =>
      new Promise<number>((resolve, reject) => {
        const socket = new WebSocket(`ws://${window.location.host}/ws`);
        socket.onclose = (event) => resolve(event.code);
        socket.onerror = () => reject(new Error("WebSocket failed to open"));
      }),
  );
  expect(code).toBe(4001);
  expect(await authenticated(page)).toBe(false);
});

test("auto-login preserves deep links", async ({ page, request }) => {
  await request.get("/__test/reset?auto_login=true");
  await page.goto("/shows/42-example/art");
  await expect(page).toHaveURL(/^http:\/\/localhost:8697\/provider\/authorize\?/);
  expect(new URL(page.url()).searchParams.get("scope")).toBe("openid profile email");
  await page.getByRole("link", { name: "Approve sign-in" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:8697/shows/42-example/art");
  expect(await authenticated(page)).toBe(true);
});

test("auto-login bypass works from any URL and lands on the login page", async ({
  page,
  request,
}) => {
  await request.get("/__test/reset?auto_login=true");
  for (const path of ["/?autologin=0", "/login?autologin=0"]) {
    await page.goto(path);
    await expect(page.getByLabel("Password")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Sign in with SSO" })).toBeVisible();
    await expect(page).toHaveURL("http://127.0.0.1:8697/login?autologin=0");
  }
});

test("RP logout revokes a copied cookie and lands on the auto-login bypass", async ({
  page,
  request,
  context,
}) => {
  await request.get("/__test/reset?auto_login=true");
  await page.goto("/");
  await page.getByRole("link", { name: "Approve sign-in" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:8697/");
  expect(await authenticated(page)).toBe(true);
  const cookie = (await context.cookies()).find((value) => value.name === "overture_token")!;
  const closeCode = await page.evaluate(async () => {
    const socket = new WebSocket(`ws://${window.location.host}/ws`);
    const closed = new Promise<number>((resolve) => {
      socket.onclose = (event) => resolve(event.code);
    });
    await new Promise<void>((resolve, reject) => {
      socket.onopen = () => resolve();
      socket.onerror = () => reject(new Error("WebSocket failed to open"));
    });
    const csrf = document.cookie
      .split("; ")
      .find((value) => value.startsWith("overture_csrf="))!
      .split("=")[1]!;
    window.history.replaceState(null, "", "/login?autologin=0");
    const response = await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "X-CSRF-Token": csrf },
    });
    const body: { redirect_url: string } = await response.json();
    return { code: await closed, url: body.redirect_url };
  });
  expect(closeCode.code).toBe(4001);
  const url = closeCode.url;
  expect(new URL(url).pathname).toBe("/provider/logout");
  await page.goto(url);
  await expect(page).toHaveURL("http://127.0.0.1:8697/login?autologin=0");
  await expect(page.getByRole("link", { name: "Sign in with SSO" })).toBeVisible();
  await expect(page.getByLabel("Password")).toHaveCount(0);
  await context.addCookies([cookie]);
  expect(await authenticated(page)).toBe(false);
});

for (const scenario of ["success", "local_logout"]) {
  test(`UI logout waits for revocation and stays logged out with auto-login enabled: ${scenario}`, async ({
    page,
    request,
  }) => {
    await request.get(`/__test/reset?auto_login=true&scenario=${scenario}`);
    await page.goto("/movies");
    await page.getByRole("link", { name: "Approve sign-in" }).click();
    await expect(page.getByLabel("Open menu")).toBeVisible();
    await expect(page.locator(".startup-overlay")).toHaveCount(0);

    let revoked!: (response: APIResponse) => void;
    const revocation = new Promise<APIResponse>((resolve) => {
      revoked = resolve;
    });
    let release!: () => void;
    const released = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/api/auth/logout", async (route) => {
      const response = await route.fetch();
      revoked(response);
      await released;
      await route.fulfill({ response });
    });
    const providerLogouts: string[] = [];
    page.on("request", (req) => {
      if (new URL(req.url()).pathname === "/provider/logout") providerLogouts.push(req.url());
    });
    await page.getByLabel("Open menu").click();
    await page.getByRole("button", { name: "Logout", exact: true }).click();
    const response = await revocation;
    expect(response.ok()).toBe(true);
    expect(await authenticated(page)).toBe(false);
    await expect(page).toHaveURL("http://127.0.0.1:8697/login?autologin=0");
    await expect(page.getByLabel("Loading Overture")).toBeVisible();
    await expect(page.getByRole("link", { name: "Sign in with SSO" })).toHaveCount(0);
    release();
    await expect(page.getByRole("link", { name: "Sign in with SSO" })).toBeVisible();
    await expect(page.getByLabel("Password")).toHaveCount(0);
    expect(providerLogouts).toHaveLength(scenario === "success" ? 1 : 0);
    await expect(page).toHaveURL("http://127.0.0.1:8697/login?autologin=0");
    await page.reload();
    await expect(page.getByRole("link", { name: "Sign in with SSO" })).toBeVisible();
    expect(await authenticated(page)).toBe(false);
  });
}
