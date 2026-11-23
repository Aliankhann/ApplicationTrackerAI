// Fails a deploy (DEPLOY=1) when vercel.json still has the __API_ORIGIN__ placeholder.
import { readFileSync } from "node:fs";

if (process.env.DEPLOY === "1") {
  const file = process.argv[2] ?? "vercel.json";
  if (readFileSync(file, "utf8").includes("__API_ORIGIN__")) {
    console.error(`${file} still contains __API_ORIGIN__; run scripts/apply-api-origin.mjs first.`);
    process.exit(1);
  }
}
