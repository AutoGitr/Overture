import { SvelteSet } from "svelte/reactivity";
import { getJobResults } from "../../generated/rest/sdk.gen";
import { sdkData } from "../rest/sdk";
import { errorMessage } from "../utils/errors";
import { orderGroups, type ResultGroup } from "../utils/resultGroups";
import {
  JobLifecycleState,
  type JobLifecycleConfig,
  type JobLifecycleEvent,
} from "./jobLifecycleState.svelte";

/** An item collected by a job, marked selected for follow-up actions. */
export type Selectable<TItem> = TItem & { selected: boolean };

/** The groups a finding belongs to, as `[key, label]` pairs. */
export type ResultGroupsOf<TItem> = (item: TItem) => (readonly [string, string])[];

/** How one collecting job names and selects its findings. */
export interface CollectingJobConfig<TEvent, TItem> extends JobLifecycleConfig<never> {
  /** Selector for the collected batch from an event. */
  items: (event: TEvent) => TItem[] | null | undefined;
  /** Selector for the running total from an event. */
  found: (event: TEvent) => number | null | undefined;
  /** The kinds a finding is shown or hidden by, such as its type and status. */
  groupsOf: ResultGroupsOf<TItem>;
  /** Group keys in the order their filters are offered; others follow by label. */
  groupOrder: readonly string[];
  /** Optional predicate choosing which kept findings start selected; all by default. */
  preselect?: (item: TItem) => boolean;
  /**
   * Optional predicate telling whether a finding can still be acted on; all
   * by default. Settled findings stay listed but never count as selected.
   */
  actionable?: (item: TItem) => boolean;
}

/** A collecting job's events also say how many findings its run has stored. */
export interface CollectingJobEvent extends JobLifecycleEvent {
  results_total?: number | null;
}

/**
 * Shared state for jobs that stream a list of findings.
 *
 * Server audit and asset scan differ only in the noun they collect
 * (`results` vs `issues`) and whether findings are filtered, so both are
 * instances of this class rather than two parallel implementations.
 *
 * Every finding of the run is held, so a selection and the actions on it
 * cover the whole run. Live batches continue the list while they follow on
 * from it; otherwise, and once the run ends, the stored findings are fetched
 * whole.
 *
 * Hiding a group hides its findings from the list and from every action:
 * what is selected is what is shown and checked, and a hidden finding keeps
 * its check for when it is shown again.
 */
export class CollectingJobState<
  TEvent extends CollectingJobEvent,
  TItem,
> extends JobLifecycleState<TEvent> {
  /** Every finding of the run, in the order found. */
  items = $state<Selectable<TItem>[]>([]);
  /** Server-reported total, which can exceed `items` while a run is streaming. */
  found = $state(0);
  /** The stored findings are being fetched. */
  loading = $state(false);
  loadError = $state("");
  /** Keys of the groups whose findings are hidden. */
  readonly hidden = new SvelteSet<string>();
  /** The findings shown, in order, with their positions in `items`. */
  readonly shown = $derived(
    this.items.flatMap((item, index) => (this.isShown(item) ? [{ index, item }] : [])),
  );
  /** Every group the findings fall into, with how many each holds. */
  readonly groups = $derived.by(() => {
    const groups: Record<string, ResultGroup> = {};
    for (const item of this.items) {
      for (const [key, label] of this.collecting.groupsOf(item)) {
        (groups[key] ??= { key, label, count: 0, shown: !this.hidden.has(key) }).count++;
      }
    }
    return orderGroups(Object.values(groups), this.collecting.groupOrder);
  });

  private runId: string | null = null;
  /** Findings the run has stored so far; a live batch is the last of them. */
  private stored = 0;
  private request: AbortController | null = null;

  private readonly collecting: CollectingJobConfig<TEvent, TItem>;
  /** Index of the finding toggled last, where a range selection starts. */
  private anchor: number | null = null;

  constructor(config: CollectingJobConfig<TEvent, TItem>) {
    super(config);
    this.collecting = config;
  }

  override get hasRun(): boolean {
    return super.hasRun || this.items.length > 0;
  }

  /** Whether a finding can still be acted on. */
  isActionable(item: TItem): boolean {
    return this.collecting.actionable?.(item) ?? true;
  }

  /** Whether no hidden group holds the finding. */
  isShown(item: TItem): boolean {
    return !this.collecting.groupsOf(item).some(([key]) => this.hidden.has(key));
  }

  /** Shown findings that can still be acted on. */
  get actionableItems(): Selectable<TItem>[] {
    return this.items.filter((item) => this.isActionable(item) && this.isShown(item));
  }

  /** Shown, selected findings that can still be acted on. */
  get selectedItems(): Selectable<TItem>[] {
    return this.actionableItems.filter((item) => item.selected);
  }

  /** Checked findings that hidden groups keep out of every action for now. */
  get hiddenSelectedCount(): number {
    return this.items.filter(
      (item) => item.selected && this.isActionable(item) && !this.isShown(item),
    ).length;
  }

  /** Show a hidden group's findings, or hide a shown group's. */
  toggleGroup(key: string) {
    if (!this.hidden.delete(key)) this.hidden.add(key);
    this.anchor = null;
  }

  /**
   * Toggle one finding. With *extend*, every shown, actionable finding from
   * the one toggled last up to this one takes the same new state, like a
   * shift-click.
   */
  toggle(index: number, extend = false) {
    const target = this.items[index];
    if (!target || !this.isActionable(target)) return;
    const selected = !target.selected;
    const anchor = extend ? (this.anchor ?? index) : index;
    const from = Math.min(anchor, index);
    const to = Math.max(anchor, index);
    this.items = this.items.map((item, position) =>
      position >= from && position <= to && this.isActionable(item) && this.isShown(item)
        ? { ...item, selected }
        : item,
    );
    this.anchor = index;
  }

  /** Select or clear every shown, actionable finding, or only those *matches* accepts. */
  setSelected(selected: boolean, matches: (item: TItem) => boolean = () => true) {
    this.items = this.items.map((item) =>
      this.isActionable(item) && this.isShown(item) && matches(item) ? { ...item, selected } : item,
    );
  }

  override handleStarted(data: TEvent) {
    super.handleStarted(data);
    this.clearFindings();
    this.follow(data, undefined);
  }

  override handleProgress(data: TEvent) {
    super.handleProgress(data);
    this.found = this.eventFound(data) ?? this.found;
    this.follow(data, this.eventItems(data));
  }

  override handleCompleted(data: TEvent) {
    super.handleCompleted(data);
    this.replaceFinalItems(data);
  }

  override handleStopped(data: TEvent) {
    super.handleStopped(data);
    this.replaceFinalItems(data);
  }

  override handleFailed(data: TEvent) {
    super.handleFailed(data);
    this.replaceFinalItems(data);
  }

  override reset() {
    super.reset();
    this.clearFindings();
  }

  /** Fetch the stored findings again after a failed request. */
  retry() {
    void this.load();
  }

  private replaceFinalItems(data: TEvent) {
    const batch = this.eventItems(data);
    if (batch && !data.run_id) this.items = this.selectable(batch);
    this.follow(data, undefined, true);
    this.found = this.eventFound(data) ?? (this.found || this.items.length);
  }

  /**
   * Take a live batch, or fetch the whole run: when the batch does not follow
   * on from the findings held, or *settled* says the stored ones are final.
   */
  private follow(data: TEvent, batch: TItem[] | undefined, settled = false) {
    if (data.run_id && data.run_id !== this.runId) {
      this.clearFindings();
      this.runId = data.run_id;
    }
    this.stored = data.results_total ?? this.stored;
    if (!this.runId) {
      if (batch) this.items = [...this.items, ...this.selectable(batch)];
      return;
    }
    const start = this.stored - (batch?.length ?? 0);
    if (batch && !settled && !this.loading && start === this.items.length) {
      this.items = [...this.items, ...this.selectable(batch)];
    } else if (settled || (!this.loading && this.items.length < this.stored)) {
      void this.load();
    }
  }

  private async load() {
    const runId = this.runId;
    if (!runId) return;
    this.request?.abort();
    const request = new AbortController();
    this.request = request;
    this.loading = true;
    this.loadError = "";
    const held = this.items.length;
    try {
      const result = await sdkData(
        getJobResults({ path: { run_id: runId }, signal: request.signal, throwOnError: true }),
      );
      if (request !== this.request) return;
      // Rows are serialized by the same backend models as the typed WS events.
      this.items = this.selectable(result.items as TItem[]);
    } catch (error) {
      if (request === this.request && !request.signal.aborted) {
        this.loadError = errorMessage(error, "Could not load the results. Please retry.");
      }
    } finally {
      if (request === this.request) {
        this.request = null;
        this.loading = false;
      }
    }
    if (this.request !== null || this.loadError) return;
    // Batches stored while the request was answered are fetched too, as long
    // as each request still brings more.
    if (this.running && this.items.length < this.stored && this.items.length > held) {
      void this.load();
    }
  }

  private clearFindings() {
    this.request?.abort();
    this.request = null;
    this.runId = null;
    this.stored = 0;
    this.found = 0;
    this.items = [];
    this.hidden.clear();
    this.anchor = null;
    this.loading = false;
    this.loadError = "";
  }

  private selectable(items: TItem[]): Selectable<TItem>[] {
    const preselect = this.collecting.preselect ?? (() => true);
    // New rows shift positions, so a range never starts from an old one.
    this.anchor = null;
    return items.map((item) => ({
      ...item,
      selected: this.isActionable(item) && preselect(item),
    }));
  }

  private eventItems(data: TEvent): TItem[] | undefined {
    return this.collecting.items(data) ?? undefined;
  }

  private eventFound(data: TEvent): number | undefined {
    return this.collecting.found(data) ?? undefined;
  }
}
