import { mount } from "svelte";
import "./app.css";
import Root from "./Root.svelte";
import { appUpdate } from "./lib/stores/appUpdate.svelte";
import { reloadOnStaleBuild } from "./lib/utils/staleBuild";

reloadOnStaleBuild(window, import.meta.url);
appUpdate.register();

const app = mount(Root, {
  target: document.getElementById("app")!,
});

export default app;
