import fs from "node:fs";
import path from "node:path";
import type * as Preset from "@docusaurus/preset-classic";
import type { Config } from "@docusaurus/types";
import { themes as prismThemes } from "prism-react-renderer";

// This runs in Node.js at build time, never in the browser.

/**
 * OvertureDB's documentation lives in its own repository and is read from the
 * sibling checkout (`../OvertureDB`), as the rest of the project expects.
 * OVERTUREDB_DOCS points elsewhere, relative to this directory.
 */
const overtureDbDocs = process.env.OVERTUREDB_DOCS ?? "../../OvertureDB/docs";
// Docusaurus loads this file from the site directory, so relative paths resolve there.
if (!fs.existsSync(path.resolve(overtureDbDocs))) {
  throw new Error(
    `OvertureDB docs not found at ${overtureDbDocs}. Clone OvertureDB beside Overture, ` +
      "or set OVERTUREDB_DOCS to its docs directory.",
  );
}

const config: Config = {
  title: "Overture",
  tagline: "Artwork, collections & themes for Plex, Jellyfin and Emby",
  favicon: "overture-tab.svg",
  url: "https://autogitr.github.io",
  baseUrl: "/Overture/",
  organizationName: "AutoGitr",
  projectName: "Overture",
  trailingSlash: false,

  onBrokenLinks: "throw",
  onBrokenAnchors: "throw",
  markdown: {
    // `.md` files are CommonMark, so plain Markdown from either repository and
    // the changelog render as they do on GitHub; `.mdx` files get MDX.
    format: "detect",
    hooks: { onBrokenMarkdownLinks: "throw" },
    mermaid: true,
  },
  future: { v4: true },

  // Brand assets come from the web app, so the site and the app never carry
  // two copies; the stylesheet bundles its fonts from there too.
  staticDirectories: ["static", "../frontend/public/brand"],

  i18n: { defaultLocale: "en", locales: ["en"] },

  presets: [
    [
      "classic",
      {
        docs: {
          path: "overture",
          routeBasePath: "overture",
          sidebarPath: "./sidebars.ts",
          editUrl: "https://github.com/AutoGitr/Overture/edit/main/docs/",
          showLastUpdateTime: true,
        },
        blog: false,
        theme: { customCss: "./src/css/custom.css" },
      } satisfies Preset.Options,
    ],
  ],

  plugins: [
    [
      "@docusaurus/plugin-content-docs",
      {
        id: "overturedb",
        path: overtureDbDocs,
        routeBasePath: "overturedb",
        sidebarPath: "./sidebars-overturedb.ts",
        editUrl: "https://github.com/AutoGitr/OvertureDB/edit/main/",
        // The sibling checkout is outside the site directory, so its Git
        // history is read from there.
        showLastUpdateTime: true,
      },
    ],
  ],

  themes: [
    "@docusaurus/theme-mermaid",
    [
      "@easyops-cn/docusaurus-search-local",
      {
        hashed: true,
        indexBlog: false,
        docsRouteBasePath: ["overture", "overturedb"],
        docsDir: ["overture", overtureDbDocs],
        docsPluginIdForPreferredVersion: "default",
      },
    ],
  ],

  themeConfig: {
    image: "overture-social.png",
    colorMode: { defaultMode: "dark", respectPrefersColorScheme: true },
    docs: { sidebar: { hideable: true, autoCollapseCategories: true } },
    navbar: {
      logo: {
        alt: "Overture",
        src: "overture-logo-inline-light.svg",
        srcDark: "overture-logo-inline-dark.svg",
        width: 132,
        height: 32,
      },
      items: [
        { type: "docSidebar", sidebarId: "docs", position: "left", label: "Overture" },
        {
          type: "docSidebar",
          sidebarId: "docs",
          docsPluginId: "overturedb",
          position: "left",
          label: "OvertureDB",
        },
        {
          type: "dropdown",
          label: "GitHub",
          position: "right",
          items: [
            { label: "Overture", href: "https://github.com/AutoGitr/Overture" },
            { label: "OvertureDB", href: "https://github.com/AutoGitr/OvertureDB" },
          ],
        },
      ],
    },
    footer: {
      style: "dark",
      links: [
        {
          title: "Overture",
          items: [
            { label: "Install", to: "/overture/install" },
            { label: "Collections", to: "/overture/features/collections" },
            { label: "Administration", to: "/overture/administration/upgrade" },
            { label: "Changelog", to: "/overture/changelog" },
          ],
        },
        {
          title: "OvertureDB",
          items: [
            { label: "Contribute", to: "/overturedb/contributing" },
            { label: "Selection guidelines", to: "/overturedb/contributing/selection-guidelines" },
            { label: "The catalog", to: "/overturedb/catalog" },
            { label: "Catalog statistics", href: "https://autogitr.github.io/OvertureDB/" },
          ],
        },
        {
          title: "Project",
          items: [
            { label: "Releases", href: "https://github.com/AutoGitr/Overture/releases" },
            {
              label: "Docker image",
              href: "https://github.com/AutoGitr/Overture/pkgs/container/overture",
            },
            {
              label: "Report an issue",
              href: "https://github.com/AutoGitr/Overture/issues/new/choose",
            },
            { label: "Support", to: "/overture/support" },
          ],
        },
      ],
      copyright:
        "Overture is licensed under AGPL-3.0 and OvertureDB under BSD 3-Clause. Built with Docusaurus.",
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.oneDark,
      additionalLanguages: ["bash", "json", "yaml", "nginx", "toml", "ini"],
    },
    tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 4 },
  } satisfies Preset.ThemeConfig,
};

export default config;
