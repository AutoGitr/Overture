import { describe, expect, it } from "vitest";
import { isWebSocketEventName, WEBSOCKET_EVENTS } from "../../generated/ws";

describe("WebSocket event validation", () => {
  it("recognises every registered event", () => {
    for (const event of WEBSOCKET_EVENTS) {
      expect(isWebSocketEventName(event)).toBe(true);
    }
  });

  it.each(["not.an.event", "", 42, null, {}, undefined])(
    "rejects an invalid event name: %j",
    (value) => {
      expect(isWebSocketEventName(value)).toBe(false);
    },
  );
});
