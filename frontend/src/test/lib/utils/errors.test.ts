import { describe, expect, it } from "vitest";
import { ApiError } from "../../../lib/rest/transport";
import { errorMessage, jobEventErrorMessage } from "../../../lib/utils/errors";

describe("errorMessage", () => {
  it("shows a redacted API error without its request ID", () => {
    expect(errorMessage(new ApiError("token=secret", 503), "fallback")).toBe("token=[REDACTED]");
  });
  it("uses redacted Error messages", () => {
    expect(errorMessage(new Error("token=secret"), "fallback")).toBe("token=[REDACTED]");
  });

  it("uses redacted string errors", () => {
    expect(errorMessage("password=hunter2", "fallback")).toBe("password=[REDACTED]");
  });

  it("falls back for empty or unknown errors", () => {
    expect(errorMessage("", "fallback")).toBe("fallback");
    expect(errorMessage({ detail: "hidden" }, "fallback")).toBe("fallback");
  });

  it("reads structured job error message", () => {
    expect(
      jobEventErrorMessage({ job: { error: { message: "typed password=hunter2" } } }, "fallback"),
    ).toBe("typed password=[REDACTED]");
  });

  it("falls back when job error is absent", () => {
    expect(jobEventErrorMessage({}, "fallback")).toBe("fallback");
    expect(jobEventErrorMessage({ job: null }, "fallback")).toBe("fallback");
    expect(jobEventErrorMessage({ job: { error: null } }, "fallback")).toBe("fallback");
  });
});
