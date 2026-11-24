import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const rootDir = path.resolve(__dirname, "../..");

export default defineConfig({
  root: __dirname,
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@hiyelx/project-engine": path.resolve(rootDir, "packages/project-engine/src/index.ts"),
      "@hiyelx/manifest-engine": path.resolve(rootDir, "packages/manifest-engine/src/index.ts"),
      "@hiyelx/graph-engine": path.resolve(rootDir, "packages/graph-engine/src/index.ts"),
      "@hiyelx/config-engine": path.resolve(rootDir, "packages/config-engine/src/index.ts"),
      "@hiyelx/telemetry": path.resolve(rootDir, "packages/telemetry/src/index.ts"),
      "@hiyelx/api-client": path.resolve(rootDir, "packages/api-client/src/index.ts"),
      "@hiyelx/workflow-engine": path.resolve(rootDir, "packages/workflow-engine/src/index.ts"),
      "@hiyelx/code-editor": path.resolve(rootDir, "packages/code-editor/src/index.ts"),
      "@hiyelx/ui": path.resolve(rootDir, "packages/ui/src/index.ts"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
  },
  build: {
    outDir: path.resolve(__dirname, "dist"),
    emptyOutDir: true,
  },
});
