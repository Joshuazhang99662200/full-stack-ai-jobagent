import { spawnSync } from "node:child_process";
const commands = [
  ["node_modules/typescript/bin/tsc", "--noEmit"],
  ["node_modules/vite/bin/vite.js", "build"],
  ["node_modules/vite/bin/vite.js", "build", "--config", "vite.lib.config.ts"],
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
