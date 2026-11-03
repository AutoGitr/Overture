import { render } from "@testing-library/svelte";
import type { Component } from "svelte";
import QueryHarness from "./QueryHarness.svelte";

/**
 * Render a component inside the app's QueryClientProvider, as Root.svelte does.
 */
export function renderWithQueryClient<Props extends Record<string, any>>(
  component: Component<Props>,
  props: Props = {} as Props,
) {
  return render(component, props, { wrapper: QueryHarness });
}
