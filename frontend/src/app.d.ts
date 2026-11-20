/// <reference types="vite-plugin-pwa/vanillajs" />

/** The release this build is, from package.json. */
declare const __APP_VERSION__: string;

declare module "*.svg" {
  const src: string;
  export default src;
}
