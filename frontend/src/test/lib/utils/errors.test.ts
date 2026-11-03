import { describe, expect, it } from "vitest";
import { ApiError } from "../../../lib/rest/transport";
import { errorMessage, jobEventErrorMessage } from "../../../lib/utils/errors";

describe("errorMessage", () => {
  it("shows an API error's message", () => {
    expect(errorMessage(new ApiError("Plex is unreachable", 503), "fallback")).toBe(
      "Plex is unreachable",
    );
  });

  it("uses Error messages and strings", () => {
    expect(errorMessage(new Error("Disk full"), "fallback")).toBe("Disk full");
    expect(errorMessage("Disk full", "fallback")).toBe("Disk full");
  });

  it("falls back for empty or unknown errors", () => {
    expect(errorMessage("", "fallback")).toBe("fallback");
    expect(errorMessage({ detail: "hidden" }, "fallback")).toBe("fallback");
  });

  it("reads structured job error message", () => {
    expect(jobEventErrorMessage({ job: { error: { message: "Disk full" } } }, "fallback")).toBe(
      "Disk full",
    );
  });

  it("falls back when job error is absent", () => {
    expect(jobEventErrorMessage({}, "fallback")).toBe("fallback");
    expect(jobEventErrorMessage({ job: null }, "fallback")).toBe("fallback");
    expect(jobEventErrorMessage({ job: { error: null } }, "fallback")).toBe("fallback");
  });
});
