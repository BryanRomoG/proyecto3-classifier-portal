import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// El alias "@" debe coincidir con vite.config.ts (usado en dev/build) y con
// tsconfig.json (usado por tsc/el editor) — sin este bloque, cualquier
// archivo que importe con "@/..." (como src/App.tsx) falla solo bajo
// vitest, no bajo vite ni tsc, lo cual es confuso de depurar.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
