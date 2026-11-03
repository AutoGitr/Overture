type Listener = ((event?: Event) => void) | null;

export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  sent: string[] = [];
  closed = false;
  onopen: Listener = null;
  onclose: Listener = null;
  onerror: Listener = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(code = 1000): void {
    if (this.closed) return;
    this.closed = true;
    this.onclose?.(new CloseEvent("close", { code }));
  }

  open(): void {
    this.onopen?.(new Event("open"));
  }

  receive(data: unknown): void {
    this.onmessage?.(
      new MessageEvent("message", {
        data: typeof data === "string" ? data : JSON.stringify(data),
      }),
    );
  }

  fail(): void {
    this.onerror?.(new Event("error"));
  }

  static reset(): void {
    FakeWebSocket.instances = [];
  }
}
