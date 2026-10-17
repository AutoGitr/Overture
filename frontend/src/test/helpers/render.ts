import { render } from "@testing-library/svelte";
import type { Component, ComponentProps } from "svelte";
import QueryHarness from "./QueryHarness.svelte";

/**
 * Render a component inside the app's QueryClientProvider, as Root.svelte does.
 */
export function renderWithQueryClient<C extends Component<any>>(
  component: C,
  props: ComponentProps<C> = {} as ComponentProps<C>,
) {
  return render(QueryHarness, { props: { component, props } });
}
