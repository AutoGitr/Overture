import type { Snippet } from "svelte";

export type NoticeTone = "success" | "info" | "warning" | "error";

export interface NoticeAction {
  label: string;
  run: () => unknown;
  /** The action's work is in flight; shown as `pendingLabel` only if it lasts. */
  pending?: boolean;
  pendingLabel?: string;
}

export interface ToastOptions {
  title?: string;
  action?: NoticeAction;
}

export interface Toast {
  id: number;
  tone: NoticeTone;
  message: string;
  title?: string;
  action?: NoticeAction;
}

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  /** Destructive confirmations get a danger button and start focused on Cancel. */
  destructive?: boolean;
}

interface ConfirmRequest extends ConfirmOptions {
  resolve: (confirmed: boolean) => void;
}

/**
 * Every toast closes itself after the same time, so none needs closing by hand.
 * Hovering or focusing one holds it open while it is read.
 */
export const TOAST_DURATION_MS = 6000;

const MAX_TOASTS = 4;

/**
 * One toast's countdown. It lives in the store, not the component, because a
 * toast is re-rendered whenever a modal opens or closes (each modal hosts its
 * own region); a component-owned timer would restart.
 */
export class ToastClock {
  private remaining = TOAST_DURATION_MS;
  private startedAt = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private stopped = false;
  private expire: () => void;

  constructor(expire: () => void) {
    this.expire = expire;
    this.release();
  }

  /** Milliseconds of the countdown already used. */
  get elapsed(): number {
    const running = this.timer === undefined ? 0 : Date.now() - this.startedAt;
    return TOAST_DURATION_MS - this.remaining + running;
  }

  /** Pause while the toast is hovered or focused. */
  hold() {
    if (this.timer === undefined) return;
    clearTimeout(this.timer);
    this.timer = undefined;
    this.remaining -= Date.now() - this.startedAt;
  }

  /** Resume the countdown where it paused. */
  release() {
    if (this.stopped || this.timer !== undefined) return;
    this.startedAt = Date.now();
    this.timer = setTimeout(this.expire, this.remaining);
  }

  stop() {
    this.stopped = true;
    clearTimeout(this.timer);
    this.timer = undefined;
  }
}

class NotificationState {
  toasts = $state<Toast[]>([]);
  /** Ongoing conditions rendered above the toasts until their owner unmounts. */
  pinned = $state<Snippet[]>([]);
  confirmRequest = $state<ConfirmRequest | null>(null);
  /**
   * Toast regions in mount order. A modal dialog makes everything outside it
   * inert, so every modal hosts its own region and only the newest one renders.
   */
  private hosts = $state<symbol[]>([]);
  private nextId = 1;
  private clocks = new Map<number, ToastClock>();

  get activeHost(): symbol | undefined {
    return this.hosts.at(-1);
  }

  show(tone: NoticeTone, message: string, options: ToastOptions = {}): number {
    const toast: Toast = {
      id: this.nextId++,
      tone,
      message,
      title: options.title,
      action: options.action,
    };
    // Repeating a message restarts it instead of stacking copies.
    const kept = this.toasts.filter((item) => item.tone !== tone || item.message !== message);
    const next = [...kept, toast].slice(-MAX_TOASTS);
    const shown = new Set(next.map((item) => item.id));
    for (const [id, clock] of this.clocks) {
      if (shown.has(id)) continue;
      clock.stop();
      this.clocks.delete(id);
    }
    this.clocks.set(toast.id, new ToastClock(() => this.dismiss(toast.id)));
    this.toasts = next;
    return toast.id;
  }

  dismiss(id: number) {
    this.clocks.get(id)?.stop();
    this.clocks.delete(id);
    this.toasts = this.toasts.filter((toast) => toast.id !== id);
  }

  /** The countdown of a toast that is currently shown. */
  clock(id: number): ToastClock {
    const clock = this.clocks.get(id);
    if (!clock) throw new Error(`Toast ${id} is not shown`);
    return clock;
  }

  /**
   * Register a toast region; returns its release callback. The app root's
   * region always sits below modal regions, whatever order they mount in.
   */
  host(id: symbol, root: boolean): () => void {
    if (root) this.hosts.unshift(id);
    else this.hosts.push(id);
    return () => {
      this.hosts = this.hosts.filter((host) => host !== id);
    };
  }

  /** Pin markup to the top of the stack; returns its release callback. */
  pin(content: Snippet): () => void {
    this.pinned.push(content);
    return () => {
      this.pinned = this.pinned.filter((item) => item !== content);
    };
  }

  confirm(options: ConfirmOptions): Promise<boolean> {
    this.settleConfirm(false);
    return new Promise((resolve) => {
      this.confirmRequest = { ...options, resolve };
    });
  }

  settleConfirm(confirmed: boolean) {
    const request = this.confirmRequest;
    this.confirmRequest = null;
    request?.resolve(confirmed);
  }
}

export const notificationState = new NotificationState();

type ToastFn = (message: string, options?: ToastOptions) => number;
export type Notifier = Record<NoticeTone, ToastFn> & { clear: () => void };

/**
 * A notification slot for one component or workflow: each new message
 * replaces the previous one, and `clear()` withdraws it when the user retries.
 */
export function createNotifier(): Notifier {
  let current: number | undefined;
  const clear = () => {
    if (current !== undefined) notificationState.dismiss(current);
    current = undefined;
  };
  const show =
    (tone: NoticeTone): ToastFn =>
    (message, options) => {
      clear();
      current = notificationState.show(tone, message, options);
      return current;
    };
  return {
    success: show("success"),
    info: show("info"),
    warning: show("warning"),
    error: show("error"),
    clear,
  };
}

export const notify = {
  success: (message: string, options?: ToastOptions) =>
    notificationState.show("success", message, options),
  info: (message: string, options?: ToastOptions) =>
    notificationState.show("info", message, options),
  warning: (message: string, options?: ToastOptions) =>
    notificationState.show("warning", message, options),
  error: (message: string, options?: ToastOptions) =>
    notificationState.show("error", message, options),
};

/** Ask before an action; resolves `true` only when the user confirms. */
export function confirmAction(options: ConfirmOptions): Promise<boolean> {
  return notificationState.confirm(options);
}
