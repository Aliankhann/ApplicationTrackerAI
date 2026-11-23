import { describe, expect, it } from "vitest";
import rawConfig from "../vercel.json?raw";
import indexHtml from "../index.html?raw";

type Header = { key: string; value: string };
const config = JSON.parse(rawConfig) as {
  rewrites: { source: string; destination: string }[];
  headers: { headers: Header[] }[];
};
const headers: Header[] = config.headers[0].headers;
const header = (key: string) => headers.find((h) => h.key === key)?.value ?? "";

describe("static hosting security (frontend/vercel.json)", () => {
  it("has a strict CSP whose connect-src still carries the API origin placeholder", () => {
    const csp = header("Content-Security-Policy");
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("script-src 'self'");
    expect(csp).toContain("connect-src 'self' __API_ORIGIN__");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).not.toContain("unsafe-inline");
  });

  it("sets nosniff, referrer, permissions, framing, and HSTS headers", () => {
    expect(header("X-Content-Type-Options")).toBe("nosniff");
    expect(header("Referrer-Policy")).toBe("no-referrer");
    expect(header("X-Frame-Options")).toBe("DENY");
    expect(header("Permissions-Policy")).toContain("camera=()");
    expect(header("Strict-Transport-Security")).toContain("max-age=31536000");
  });

  it("rewrites non-asset paths to the SPA entry", () => {
    expect(config.rewrites).toEqual([{ source: "/((?!assets/).*)", destination: "/index.html" }]);
  });

  it("index.html has no inline scripts", () => {
    expect(indexHtml).not.toMatch(/<script(?![^>]*\ssrc=)[^>]*>/);
  });
});
