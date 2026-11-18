// Fails a deploy (DEPLOY=1) when the built _headers still has the __API_ORIGIN__ placeholder.
import { readFileSync } from "node:fs";

if (process.env.DEPLOY === "1") {
  const file = process.argv[2] ?? "dist/_headers";
  if (readFileSync(file, "utf8").includes("__API_ORIGIN__")) {
    console.error(`${file} still contains __API_ORIGIN__; substitute the API origin first.`);
    process.exit(1);
  }
}
