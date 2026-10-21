import { describe, expect, it } from "vitest";
import { redactText } from "../../../lib/utils/redact";

describe("redactText", () => {
  it("redacts query secrets without removing safe query fields", () => {
    expect(redactText("/x?token=abc123&title=Alien&api_key=tmdb-secret")).toBe(
      "/x?token=[REDACTED]&title=Alien&api_key=[REDACTED]",
    );
  });

  it("redacts credential-like key value pairs", () => {
    const redacted = redactText("authorization: Bearer abc password=hunter2 csrf=csrf-token");

    expect(redacted).not.toContain("abc");
    expect(redacted).not.toContain("hunter2");
    expect(redacted).not.toContain("csrf-token");
    expect(redacted).toContain("[REDACTED]");
  });

  it("redacts URL user info, direct Plex hostnames, and JWT-shaped tokens", () => {
    const jwt = "eyJaaaaaaaaaaa.bbbbbbbbbbbbb.ccccccccccccc";
    const message = `http://user:pass@example.test ${jwt} https://1-2-3-4.abc.plex.direct:32400/path`;

    expect(redactText(message)).toBe(
      "http://[REDACTED]@example.test [REDACTED] https://[REDACTED].plex.direct",
    );
  });
});
