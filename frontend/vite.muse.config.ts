import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [tailwindcss()],
  build: {
    outDir: "muse-lib",
    lib: {
      entry: "src/muse/index.ts",
      formats: ["es"],
      fileName: "muse",
      cssFileName: "muse",
    },
    rollupOptions: {
      external: ["react", "react/jsx-runtime", "@tanstack/react-query"],
    },
  },
});
