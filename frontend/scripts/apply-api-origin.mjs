// Deploy step: writes the API origin (from API_ORIGIN, or the origin of VITE_API_BASE_URL) into
// vercel.json in place, replacing the __API_ORIGIN__ placeholder in the CSP connect-src.
// Run before `vercel deploy`, then `DEPLOY=1 pnpm check:deploy` to prove no placeholder is left.
import { readFileSync, writeFileSync } from "node:fs";

const file = process.argv[2] ?? "vercel.json";
const raw = process.env.API_ORIGIN ?? process.env.VITE_API_BASE_URL ?? "";
let origin;
try {
  const url = new URL(raw);
  if (url.protocol !== "https:") throw new Error("not https");
  origin = url.origin;
} catch {
  console.error("Set API_ORIGIN (or VITE_API_BASE_URL) to the public https URL of the API.");
  process.exit(1);
}
writeFileSync(file, readFileSync(file, "utf8").replaceAll("__API_ORIGIN__", origin));
