#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const pagesBase = "/wudup/";
const htmlPath = resolve("dist", "index.html");
const html = readFileSync(htmlPath, "utf8");
const failures = [];

if (html.includes("impeccable-live")) {
  failures.push("contains local live-reload markers");
}

if (/https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?\b/i.test(html)) {
  failures.push("contains localhost or loopback URLs");
}

if (/<script\b[^>]*\bsrc=["']http:\/\//i.test(html)) {
  failures.push("contains an insecure external script");
}

if (html.includes("/src/main.ts")) {
  failures.push("contains the Vite dev source entrypoint");
}

const assetRefs = [...html.matchAll(/\b(?:src|href)=["']([^"']*\/assets\/[^"']+)["']/g)]
  .map((match) => match[1]);

if (assetRefs.length === 0) {
  failures.push("contains no built asset references");
}

for (const ref of assetRefs) {
  if (!ref.startsWith(pagesBase)) {
    failures.push(`asset reference is missing ${pagesBase} base: ${ref}`);
  }
}

if (failures.length > 0) {
  console.error(`Static demo artifact check failed for ${htmlPath}:`);
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log(`Static demo artifact check passed for ${htmlPath}`);
