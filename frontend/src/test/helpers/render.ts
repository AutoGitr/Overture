import { fireEvent, render, screen } from "@testing-library/svelte";
import type { Component } from "svelte";
import QueryHarness from "./QueryHarness.svelte";

/** Open a `Select` combobox and pick the named option. */
export async function chooseOption(control: HTMLElement, option: string | RegExp) {
  await fireEvent.click(control);
  await fireEvent.click(await screen.findByRole("option", { name: option }));
}

/**
 * Render a component inside the app's QueryClientProvider, as Root.svelte does.
 *
 * Props reach the component as accessors, as with `bind:`, so components that
 * edit a bindable draft in place see it owned by the test, as by their parents.
 */
export function renderWithQueryClient<Props extends Record<string, any>>(
  component: Component<Props>,
  props: Props = {} as Props,
) {
  const bound = Object.defineProperties(
    {},
    Object.fromEntries(
      Object.keys(props).map((key) => [
        key,
        {
          enumerable: true,
          get: () => props[key],
          set: (value: unknown) => Object.assign(props, { [key]: value }),
        },
      ]),
    ),
  ) as Props;
  return render(component, bound, { wrapper: QueryHarness });
}
