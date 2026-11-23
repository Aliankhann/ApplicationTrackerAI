import { spawnSync } from "node:child_process";
import { copyFileSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("deploy scripts", () => {
  const apply = (file: string, env: Record<string, string>) =>
    spawnSync("node", ["scripts/apply-api-origin.mjs", file], { env: { PATH: process.env.PATH, ...env } });
  const check = (file: string, deploy: boolean) =>
    spawnSync("node", ["scripts/check-deploy-headers.mjs", file], {
      env: { PATH: process.env.PATH, ...(deploy ? { DEPLOY: "1" } : {}) },
    }).status;

  it("the deploy check fails while the placeholder survives, and passes after substitution", () => {
    const file = join(mkdtempSync(join(tmpdir(), "vercel-")), "vercel.json");
    copyFileSync("vercel.json", file);
    expect(check(file, true)).toBe(1);
    expect(check(file, false)).toBe(0);
    expect(apply(file, { VITE_API_BASE_URL: "https://api.example.test/v1" }).status).toBe(0);
    expect(readFileSync(file, "utf8")).toContain("connect-src 'self' https://api.example.test;");
    expect(check(file, true)).toBe(0);
  });

  it("refuses a missing or non-https API origin instead of leaving the placeholder", () => {
    const file = join(mkdtempSync(join(tmpdir(), "vercel-")), "vercel.json");
    copyFileSync("vercel.json", file);
    expect(apply(file, {}).status).toBe(1);
    expect(apply(file, { API_ORIGIN: "http://api.example.test" }).status).toBe(1);
    expect(readFileSync(file, "utf8")).toContain("__API_ORIGIN__");
  });
});
