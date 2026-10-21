import { Resvg } from "@resvg/resvg-js";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { format } from "prettier";

const publicDir = new URL("../public/", import.meta.url);
const designDir = new URL("../design/", import.meta.url);
const mark = await readFile(new URL("overture-mark.svg", designDir), "utf8");
const wordmark = await readFile(new URL("overture-wordmark.svg", designDir), "utf8");
const dbWordmark = await readFile(new URL("overturedb-wordmark.svg", designDir), "utf8");
const tagline = await readFile(new URL("overture-tagline.svg", designDir), "utf8");
const dark = ["#9ca1aa", "#bdb7ab", "#d8c7a3"] as const;
const light = ["#626a76", "#746e62", "#806844"] as const;
const background = "#0a0c10";

function heightAtWidth(source: string, width: number): number {
  const bounds = new Resvg(source, { font: { loadSystemFonts: false } }).getBBox();
  if (!bounds) throw new Error("Brand source has no visible geometry");
  return (width * bounds.height) / bounds.width;
}

const inlineTextHeight = heightAtWidth(wordmark, 480);
const bannerTitleHeight = heightAtWidth(wordmark, 580);
const bannerTaglineHeight = 90;
const bannerTextTop = (256 - bannerTitleHeight - 32 - bannerTaglineHeight) / 2;

function svg(width: number, height: number, content: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${content}</svg>`;
}

function place(source: string, x: number, y: number, width: number, height: number): string {
  return source.replace(/<svg\b[^>]*>/, (root) =>
    root
      .replace(/\s(?:width|height)="[^"]*"/g, "")
      .replace(
        "<svg ",
        `<svg x="${x}" y="${y}" width="${width}" height="${height}" preserveAspectRatio="xMinYMid" `,
      ),
  );
}

function palette(source: string, colors: readonly string[]): string {
  return dark.reduce((result, color, index) => result.replaceAll(color, colors[index]!), source);
}

function stackedLogo(themedMark: string, themedWordmark: string): string {
  const textHeight = heightAtWidth(themedWordmark, 480);
  const top = (344 - 192 - 48 - textHeight) / 2;
  return svg(
    480,
    344,
    place(themedMark, 144, top, 192, 192) +
      place(themedWordmark, 0, top + 192 + 48, 480, textHeight),
  );
}

async function saveSvg(name: string, source: string): Promise<void> {
  await writeFile(new URL(name, publicDir), await format(source, { parser: "html" }));
}

async function savePng(name: string, source: string, size?: number): Promise<void> {
  const renderer = new Resvg(source, {
    font: { loadSystemFonts: false },
    ...(size ? { fitTo: { mode: "width", value: size } } : {}),
  });
  await writeFile(new URL(name, publicDir), renderer.render().asPng());
}

await mkdir(new URL("brand/", publicDir), { recursive: true });
for (const [theme, colors] of [
  ["dark", dark],
  ["light", light],
] as const) {
  const themedMark = palette(mark, colors);
  const themedWordmark = wordmark.replaceAll(
    "currentColor",
    theme === "dark" ? dark[2] : "#292b31",
  );
  const themedTagline = tagline.replaceAll("currentColor", theme === "dark" ? dark[1] : light[1]);
  const inline = svg(
    640,
    128,
    place(themedMark, 0, 0, 128, 128) +
      place(themedWordmark, 160, (128 - inlineTextHeight) / 2, 480, inlineTextHeight),
  );
  const stacked = stackedLogo(themedMark, themedWordmark);
  const dbStacked = stackedLogo(
    themedMark,
    dbWordmark.replaceAll("currentColor", theme === "dark" ? dark[2] : "#292b31"),
  );
  await saveSvg(`brand/overturedb-logo-stacked-${theme}.svg`, dbStacked);
  await savePng(`brand/overturedb-logo-stacked-${theme}.png`, dbStacked, 960);
  const banner = svg(
    880,
    256,
    place(themedMark, 0, 0, 256, 256) +
      place(themedWordmark, 300, bannerTextTop, 580, bannerTitleHeight) +
      place(themedTagline, 300, bannerTextTop + bannerTitleHeight + 32, 580, bannerTaglineHeight),
  );

  for (const [name, source, size] of [
    ["logo", themedMark, 512],
    ["logo-inline", inline, 1280],
    ["logo-stacked", stacked, 960],
    ["banner", banner, 1760],
  ] as const) {
    await saveSvg(`brand/overture-${name}-${theme}.svg`, source);
    await savePng(`brand/overture-${name}-${theme}.png`, source, size);
  }

  if (theme === "dark") {
    await saveSvg(
      "brand/overture-logo-inline.svg",
      adaptive(inline.replaceAll(`fill="${dark[2]}"`, 'fill="currentColor"')),
    );
    await savePng(
      "og.png",
      svg(
        1200,
        630,
        `<rect width="1200" height="630" fill="${background}"/>` +
          place(banner, 160, 187, 880, 256),
      ),
    );
  }
}

// Embedded SVG media queries inherit the host's color-scheme, including the
// app's explicit theme. Browser tabs use the browser's own color scheme.
function adaptive(source: string): string {
  const styles = `<style>:root{color:#292b31}${light.map((color, index) => `.tone-${index}{stroke:${color}}`).join("")}@media(prefers-color-scheme:dark){:root{color:${dark[2]}}${dark.map((color, index) => `.tone-${index}{stroke:${color}}`).join("")}}</style>`;
  return dark
    .reduce(
      (result, color, index) => result.replaceAll(`stroke="${color}"`, `class="tone-${index}"`),
      source,
    )
    .replace(/(<svg[^>]*>)/, `$1${styles}`);
}

await saveSvg("favicon.svg", adaptive(mark));
// Keep three distinct rings and open gaps at browser-tab sizes.
const tabMark = svg(
  16,
  16,
  `<g fill="none" stroke="currentColor" stroke-width="1.5"><rect x="0.75" y="0.75" width="14.5" height="14.5" rx="3.75"/><rect x="3" y="3" width="10" height="10" rx="2.5"/><rect x="5.25" y="5.25" width="5.5" height="5.5" rx="1.25"/></g>`,
);
await saveSvg(
  "favicon-tab.svg",
  tabMark.replace(
    /(<svg[^>]*>)/,
    "$1<style>:root{color:#000}@media(prefers-color-scheme:dark){:root{color:#fff}}</style>",
  ),
);
for (const size of [16, 32]) {
  await savePng(`favicon-${size}.png`, tabMark.replaceAll("currentColor", "#000"), size);
}

// Ordinary icons are transparent. Launcher-specific assets are full bleed;
// the 56% square fits entirely inside the maskable 80%-diameter safe circle.
const icon = svg(512, 512, place(mark, 32, 32, 448, 448));
for (const size of [192, 512]) {
  await savePng(`pwa-${size}x${size}.png`, icon, size);
}
await savePng(
  "apple-touch-icon.png",
  svg(
    512,
    512,
    `<rect width="512" height="512" fill="${background}"/>` + place(mark, 64, 64, 384, 384),
  ),
  180,
);
await savePng(
  "pwa-maskable-512x512.png",
  svg(
    512,
    512,
    `<rect width="512" height="512" fill="${background}"/>` +
      place(mark, 112.64, 112.64, 286.72, 286.72),
  ),
);

process.stdout.write(`Brand assets exported to ${fileURLToPath(publicDir)}\n`);
