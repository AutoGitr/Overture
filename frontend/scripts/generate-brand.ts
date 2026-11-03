import { Resvg } from "@resvg/resvg-js";
import { execFileSync } from "node:child_process";
import { access, copyFile, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const publicDir = new URL("../public/", import.meta.url);
const designDir = new URL("../design/", import.meta.url);
const themes = {
  dark: { tones: ["#9ca1aa", "#bdb7ab", "#d8c7a3"], text: "#d8c7a3" },
  light: { tones: ["#626a76", "#746e62", "#806844"], text: "#292b31" },
} as const;
const background = "#0a0c10";
const renderOptions = { font: { loadSystemFonts: false }, shapeRendering: 2 } as const;
type Product = "overture" | "overturedb";
type Theme = keyof typeof themes;
type Graphic = { source: string; width: number; height: number };

function number(value: number): string {
  return String(Number(value.toFixed(6)));
}

function svg(width: number, height: number, content: string): Graphic {
  return {
    width,
    height,
    source: `<svg xmlns="http://www.w3.org/2000/svg" width="${number(width)}" height="${number(height)}" viewBox="0 0 ${number(width)} ${number(height)}">${content}</svg>`,
  };
}

async function outlined(name: string): Promise<Graphic> {
  const source = await readFile(new URL(`${name}.svg`, designDir), "utf8");
  const bounds = new Resvg(source, renderOptions).getBBox();
  if (!bounds) throw new Error(`Empty brand source: ${name}`);
  return {
    width: bounds.width,
    height: bounds.height,
    source: source.replace(
      /<svg\b[^>]*>/,
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${[bounds.x, bounds.y, bounds.width, bounds.height].map(number).join(" ")}">`,
    ),
  };
}

function mark(product: Product, small = false): Graphic & { radius: number } {
  const stroke = small ? 1.25 : 2.3;
  const radii = small ? [7.375, 4.875, 2.375] : product === "overture" ? [23, 18, 13] : [23, 16, 9];
  const corners = small ? [3.5, 2.5, 1.5] : [8.8, 7, 5.2];
  const halfHeight = radii[0]! + stroke / 2;
  const halfWidth =
    product === "overture" ? halfHeight : (radii[0]! * Math.sqrt(3)) / 2 + stroke / 2;
  const paths = themes.dark.tones
    .map((color, index) => {
      if (product === "overture") {
        const half = radii[index]!;
        const corner = corners[index]!;
        return `<rect x="${number(-half)}" y="${number(-half)}" width="${number(half * 2)}" height="${number(half * 2)}" rx="${number(corner)}" stroke="${color}"/>`;
      }
      const radius = radii[index]!;
      const x = (radius * Math.sqrt(3)) / 2;
      const points = [
        [0, -radius],
        [x, -radius / 2],
        [x, radius / 2],
        [0, radius],
        [-x, radius / 2],
        [-x, -radius / 2],
      ];
      return `<polygon points="${points.map((point) => point.map(number).join(",")).join(" ")}" stroke="${color}"/>`;
    })
    .join("");
  return {
    ...svg(
      halfWidth * 2,
      halfHeight * 2,
      `<g transform="translate(${number(halfWidth)} ${number(halfHeight)})" fill="none" stroke-width="${stroke}" stroke-linejoin="round" shape-rendering="geometricPrecision">${paths}</g>`,
    ),
    radius:
      product === "overture"
        ? Math.sqrt(2) * (radii[0]! - corners[0]!) + corners[0]! + stroke / 2
        : halfHeight,
  };
}

function place(graphic: Graphic, x: number, y: number, width: number, height: number): string {
  return graphic.source.replace(/<svg\b[^>]*>/, (root) =>
    root
      .replace(/\s(?:width|height)="[^"]*"/g, "")
      .replace(
        "<svg ",
        `<svg x="${number(x)}" y="${number(y)}" width="${number(width)}" height="${number(height)}" preserveAspectRatio="xMidYMid meet" `,
      ),
  );
}

function themed(source: string, theme: Theme): string {
  return themes.dark.tones
    .reduce((result, color, index) => result.replaceAll(color, themes[theme].tones[index]!), source)
    .replaceAll("currentColor", themes[theme].text);
}

function adaptive(source: string): string {
  const rules = (theme: Theme) =>
    `:root{color:${themes[theme].text}}${themes[theme].tones.map((color, index) => `.tone-${index}{stroke:${color}}`).join("")}`;
  return themes.dark.tones
    .reduce(
      (result, color, index) => result.replaceAll(`stroke="${color}"`, `class="tone-${index}"`),
      source,
    )
    .replace(
      /(<svg[^>]*>)/,
      `$1<style>${rules("light")}@media(prefers-color-scheme:dark){${rules("dark")}}</style>`,
    );
}

async function saveSvg(name: string, source: string): Promise<void> {
  const formatted = execFileSync("bun", ["fmt", "--stdin-filepath", `${name}.html`], {
    input: source,
    encoding: "utf8",
    cwd: fileURLToPath(new URL("../", import.meta.url)),
  });
  await writeFile(new URL(name, publicDir), formatted);
}

async function savePng(name: string, source: string, width: number): Promise<void> {
  const renderer = new Resvg(source, { ...renderOptions, fitTo: { mode: "width", value: width } });
  await writeFile(new URL(name, publicDir), renderer.render().asPng());
}

function lockups(icon: Graphic, wordmark: Graphic, tagline: Graphic) {
  const textHeight = (wordmark.height / wordmark.width) * 480;
  const iconWidth = (icon.width / icon.height) * 128;
  const titleHeight = (wordmark.height / wordmark.width) * 580;
  const taglineHeight = (tagline.height / tagline.width) * 580;
  const textBlockHeight = titleHeight + 32 + taglineHeight;
  const bannerHeight = Math.max(256, textBlockHeight);
  const bannerIconWidth = (icon.width / icon.height) * 256;
  const bannerTextX = bannerIconWidth + 44;
  return {
    logo: icon,
    "logo-inline": svg(
      iconWidth + 32 + 480,
      128,
      place(icon, 0, 0, iconWidth, 128) +
        place(wordmark, iconWidth + 32, (128 - textHeight) / 2, 480, textHeight),
    ),
    "logo-stacked": svg(
      480,
      192 + 48 + textHeight,
      place(icon, (480 - iconWidth * 1.5) / 2, 0, iconWidth * 1.5, 192) +
        place(wordmark, 0, 240, 480, textHeight),
    ),
    banner: svg(
      bannerTextX + 580,
      bannerHeight,
      place(icon, 0, (bannerHeight - 256) / 2, bannerIconWidth, 256) +
        place(wordmark, bannerTextX, (bannerHeight - textBlockHeight) / 2, 580, titleHeight) +
        place(
          tagline,
          bannerTextX,
          (bannerHeight - textBlockHeight) / 2 + titleHeight + 32,
          580,
          taglineHeight,
        ),
    ),
  };
}

const tagline = await outlined("overture-tagline");
await mkdir(new URL("brand/", publicDir), { recursive: true });
for (const product of ["overture", "overturedb"] as const) {
  const icon = mark(product);
  const tab = mark(product, true);
  const wordmark = await outlined(`${product}-wordmark`);
  const assets = lockups(icon, wordmark, tagline);
  await saveSvg(`../design/${product}-mark.svg`, icon.source);
  for (const [name, graphic] of Object.entries(assets)) {
    await saveSvg(`brand/${product}-${name}.svg`, adaptive(graphic.source));
    for (const theme of ["dark", "light"] as const) {
      const source = themed(graphic.source, theme);
      await saveSvg(`brand/${product}-${name}-${theme}.svg`, source);
      await savePng(
        `brand/${product}-${name}-${theme}.png`,
        source,
        name === "logo" ? 512 : Math.round(graphic.width * 2),
      );
    }
  }
  await saveSvg(`brand/${product}-tab.svg`, adaptive(tab.source));
  for (const theme of ["dark", "light"] as const) {
    for (const size of [16, 32, 48]) {
      const square = svg(size, size, place(tab, 0, 0, size, size));
      await savePng(
        `brand/${product}-tab-${size}-${theme}.png`,
        themed(square.source, theme),
        size,
      );
    }
  }
  const banner = assets.banner;
  const social = svg(
    1200,
    630,
    `<rect width="1200" height="630" fill="${background}"/>` +
      place(
        banner,
        (1200 - banner.width) / 2,
        (630 - banner.height) / 2,
        banner.width,
        banner.height,
      ),
  );
  await savePng(`brand/${product}-social.png`, themed(social.source, "dark"), 1200);
  if (product === "overture") {
    await savePng("og.png", themed(social.source, "dark"), 1200);
    await saveSvg("favicon.svg", adaptive(svg(16, 16, place(tab, 0, 0, 16, 16)).source));
    for (const theme of ["dark", "light"] as const) {
      for (const size of [16, 32]) {
        await savePng(
          `favicon-${size}${theme === "dark" ? "-dark" : ""}.png`,
          themed(svg(size, size, place(tab, 0, 0, size, size)).source, theme),
          size,
        );
      }
    }
    for (const size of [192, 512]) {
      await savePng(
        `pwa-${size}x${size}.png`,
        themed(svg(size, size, place(icon, 0, 0, size, size)).source, "dark"),
        size,
      );
    }
    const safeSize = (512 * 0.4 * icon.width) / icon.radius;
    const launcher = svg(
      512,
      512,
      `<rect width="512" height="512" fill="${background}"/>` +
        place(icon, (512 - safeSize) / 2, (512 - safeSize) / 2, safeSize, safeSize),
    );
    const apple = svg(
      512,
      512,
      `<rect width="512" height="512" fill="${background}"/>` +
        place(icon, 51.2, 51.2, 409.6, 409.6),
    );
    await savePng("apple-touch-icon.png", themed(apple.source, "dark"), 180);
    await savePng("pwa-maskable-512x512.png", themed(launcher.source, "dark"), 512);
  }
}
if (process.argv.includes("--sync-db")) {
  const repo = new URL("../../../OvertureDB/", import.meta.url);
  await access(new URL("pyproject.toml", repo));
  const destination = new URL(".github/brand/", repo);
  await mkdir(destination, { recursive: true });
  for (const name of await readdir(new URL("brand/", publicDir))) {
    if (name.startsWith("overturedb-")) {
      await copyFile(new URL(`brand/${name}`, publicDir), new URL(name, destination));
    }
  }
}
process.stdout.write(`Brand assets exported to ${fileURLToPath(publicDir)}\n`);
