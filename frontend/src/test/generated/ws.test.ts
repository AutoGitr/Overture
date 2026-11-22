import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  isServerWebSocketMessage,
  isWebSocketEventName,
  WEBSOCKET_EVENTS,
} from "../../generated/ws";

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

/** Frames shaped like an envelope, any field missing or of another type. */
const envelope = fc.record(
  {
    event: fc.oneof(fc.constantFrom(...WEBSOCKET_EVENTS, "ping"), fc.string()),
    epoch: fc.oneof(fc.string(), fc.integer()),
    sequence: fc.oneof(fc.integer(), fc.string()),
    data: fc.jsonValue(),
  },
  { requiredKeys: [] },
);

describe("isServerWebSocketMessage for any frame", () => {
  it("accepts only a ping or an envelope naming a known event, and never throws", () => {
    fc.assert(
      fc.property(fc.oneof(fc.jsonValue(), envelope), (frame) => {
        if (!isServerWebSocketMessage(frame)) return;
        if (frame.event === "ping") return;
        expect(WEBSOCKET_EVENTS).toContain(frame.event);
        expect(typeof frame.epoch).toBe("string");
        expect(typeof frame.sequence).toBe("number");
      }),
    );
  });
});
