import { defineConfig } from "vite";
export default defineConfig({
  build: {
    outDir: "lib",
    lib: {
      entry: "src/Console.tsx",
      formats: ["es"],
      fileName: "console",
      cssFileName: "console",
    },
    rollupOptions: { external: ["react", "react/jsx-runtime"] },
  },
});
