import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@hiyelx/project-engine": path.resolve(__dirname, "packages/project-engine/src/index.ts"),
      "@hiyelx/manifest-engine": path.resolve(__dirname, "packages/manifest-engine/src/index.ts"),
      "@hiyelx/graph-engine": path.resolve(__dirname, "packages/graph-engine/src/index.ts"),
      "@hiyelx/config-engine": path.resolve(__dirname, "packages/config-engine/src/index.ts"),
      "@hiyelx/telemetry": path.resolve(__dirname, "packages/telemetry/src/index.ts"),
      "@hiyelx/code-editor": path.resolve(__dirname, "packages/code-editor/src/index.ts"),
      "@hiyelx/ui": path.resolve(__dirname, "packages/ui/src/index.ts"),
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
  },
});
