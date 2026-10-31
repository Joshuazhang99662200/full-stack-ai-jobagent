import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests",
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:5178",
    launchOptions: { executablePath: process.env.CONSOLE_BROWSER },
  },
  webServer: {
    command: "npm run dev -- --port 5178",
    url: "http://127.0.0.1:5178",
    reuseExistingServer: !process.env.CI,
  },
});
