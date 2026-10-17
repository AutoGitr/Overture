import {
  JobLifecycleState,
  type JobLifecycleConfig,
  type JobLifecycleEvent,
} from "./jobLifecycleState.svelte";
import { JobResultPage } from "./jobResultPage.svelte";

/** An item collected by a job, marked selected for follow-up actions. */
export type Selectable<TItem> = TItem & { selected: boolean };

/** Findings of one kind, which the results list selects together. */
export interface SelectionGroup {
  key: string;
  label: string;
  /** Actionable findings in the group. */
  total: number;
  /** How many of them are selected. */
  selected: number;
}

/** The selection groups a finding belongs to, as `[key, label]` pairs. */
export type SelectionGroupsOf<TItem> = (item: TItem) => (readonly [string, string])[];

/** How one collecting job names and selects its findings. */
export interface CollectingJobConfig<TEvent, TItem> extends JobLifecycleConfig<never> {
  /** Event field carrying the collected batch. */
  itemsKey: keyof TEvent;
  /** Event field carrying the running total. */
  foundKey: keyof TEvent;
  /** Optional predicate choosing which kept findings start selected; all by default. */
  preselect?: (item: TItem) => boolean;
  /**
   * Optional predicate telling whether a finding can still be acted on; all
   * by default. Settled findings stay listed but never count as selected.
   */
  actionable?: (item: TItem) => boolean;
}

/**
 * Shared state for jobs that stream a list of findings.
 *
 * Server audit and asset scan differ only in the noun they collect
 * (`results` vs `issues`) and whether findings are filtered, so both are
 * instances of this class rather than two parallel implementations.
 */
export class CollectingJobState<
  TEvent extends JobLifecycleEvent,
  TItem,
> extends JobLifecycleState<TEvent> {
  /** Findings collected so far, in arrival order. */
  items = $state<Selectable<TItem>[]>([]);
  /** Server-reported total, which can exceed `items` while a run is streaming. */
  found = $state(0);
  readonly page = new JobResultPage<TItem>((items) => {
    this.items = this.selectable(items);
  });

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

  /** Findings that can still be acted on. */
  get actionableItems(): Selectable<TItem>[] {
    return this.items.filter((item) => this.isActionable(item));
  }

  /** Selected findings that can still be acted on. */
  get selectedItems(): Selectable<TItem>[] {
    return this.items.filter((item) => item.selected && this.isActionable(item));
  }

  /**
   * Toggle one finding. With *extend*, every actionable finding from the one
   * toggled last up to this one takes the same new state, like a shift-click.
   */
  toggle(index: number, extend = false) {
    const target = this.items[index];
    if (!target || !this.isActionable(target)) return;
    const selected = !target.selected;
    const anchor = extend ? (this.anchor ?? index) : index;
    const from = Math.min(anchor, index);
    const to = Math.max(anchor, index);
    this.items = this.items.map((item, position) =>
      position >= from && position <= to && this.isActionable(item) ? { ...item, selected } : item,
    );
    this.anchor = index;
  }

  /** Select or clear every actionable finding, or only those *matches* accepts. */
  setSelected(selected: boolean, matches: (item: TItem) => boolean = () => true) {
    this.items = this.items.map((item) =>
      this.isActionable(item) && matches(item) ? { ...item, selected } : item,
    );
  }

  /**
   * The groups the actionable findings fall into, in the order *order* lists
   * their keys; groups it does not list follow by label.
   */
  selectionGroups(groupsOf: SelectionGroupsOf<TItem>, order: readonly string[]): SelectionGroup[] {
    const groups: Record<string, SelectionGroup> = {};
    for (const item of this.actionableItems) {
      for (const [key, label] of groupsOf(item)) {
        const group = (groups[key] ??= { key, label, total: 0, selected: 0 });
        group.total++;
        if (item.selected) group.selected++;
      }
    }
    const rank = (group: SelectionGroup) => {
      const index = order.indexOf(group.key);
      return index === -1 ? order.length : index;
    };
    return Object.values(groups).sort(
      (left, right) => rank(left) - rank(right) || left.label.localeCompare(right.label),
    );
  }

  /** Select every finding in a group, or clear them when all already are. */
  toggleGroup(groupsOf: SelectionGroupsOf<TItem>, key: string) {
    const inGroup = (item: TItem) => groupsOf(item).some(([groupKey]) => groupKey === key);
    const members = this.actionableItems.filter(inGroup);
    this.setSelected(!members.every((item) => item.selected), inGroup);
  }

  override handleStarted(data: TEvent) {
    super.handleStarted(data);
    this.found = 0;
    this.items = [];
    this.page.reset();
    this.page.update(data);
  }

  override handleProgress(data: TEvent) {
    super.handleProgress(data);
    this.found = this.eventFound(data) ?? this.found;
    const batch = this.eventItems(data);
    if (batch) this.items = [...this.items, ...this.selectable(batch)].slice(-this.page.size);
    this.page.update(data);
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
    this.found = 0;
    this.items = [];
    this.anchor = null;
    this.page.reset();
  }

  private replaceFinalItems(data: TEvent) {
    const batch = this.eventItems(data);
    if (batch) this.items = this.selectable(batch.slice(0, this.page.size));
    this.found = this.eventFound(data) ?? (this.found || this.items.length);
    this.page.update(data, true);
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
    return (data[this.collecting.itemsKey] as TItem[] | null | undefined) ?? undefined;
  }

  private eventFound(data: TEvent): number | undefined {
    return (data[this.collecting.foundKey] as number | null | undefined) ?? undefined;
  }
}
