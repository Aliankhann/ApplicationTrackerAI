import { describe, expect, it } from "vitest";
import headers from "../public/_headers?raw";
import indexHtml from "../index.html?raw";

describe("static hosting security", () => {
  it("has a strict CSP in public/_headers", () => {
    expect(headers).toContain("script-src 'self'");
    expect(headers).toContain("connect-src 'self' __API_ORIGIN__");
    expect(headers).toContain("object-src 'none'");
  });

  it("index.html has no inline scripts", () => {
    expect(indexHtml).not.toMatch(/<script(?![^>]*\ssrc=)[^>]*>/);
  });
});
