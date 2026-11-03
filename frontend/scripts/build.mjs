import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync } from "node:fs";
const commands = [
  ["node_modules/typescript/bin/tsc", "--noEmit"],
  ["node_modules/vite/bin/vite.js", "build"],
  ["node_modules/vite/bin/vite.js", "build", "--config", "vite.lib.config.ts"],
  ["node_modules/vite/bin/vite.js", "build", "--config", "vite.muse.config.ts"],
  [
    "node_modules/typescript/bin/tsc",
    "--emitDeclarationOnly",
    "--outDir",
    "lib",
  ],
];
for (const args of commands) {
  const result = spawnSync(process.execPath, args, { stdio: "inherit" });
  if (result.status !== 0) process.exit(result.status || 1);
}

for (const output of ["dist", "lib", "muse-lib"]) {
  for (const name of [
    "LICENSE",
    "NOTICE",
    "COMMERCIAL_LICENSE.md",
    "LICENSES/Apache-2.0.txt",
  ]) {
    const target = new URL(`../${output}/${name}`, import.meta.url);
    mkdirSync(new URL(".", target), { recursive: true });
    copyFileSync(new URL(`../../${name}`, import.meta.url), target);
  }
  copyFileSync(
    new URL("../THIRD_PARTY_NOTICES.md", import.meta.url),
    new URL(`../${output}/THIRD_PARTY_NOTICES.md`, import.meta.url),
  );
}
