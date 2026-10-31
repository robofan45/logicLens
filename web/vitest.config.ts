// six-gate-build layout: Vitest for unit + integration tests.
//   npm run test:unit          fast TDD loop (gate 1)
//   npm run test:integration   real wiring across modules (gate 2)
//   npm run coverage           coverage report
// Engine tests run in Node. UI tests opt into a DOM per file with a
// `// @vitest-environment jsdom` docblock at the top of the test file.
import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: {
    include: ["tests/**/*.test.{ts,tsx}"],
    environment: "node",
    restoreMocks: true,
    testTimeout: 60_000,
    coverage: {
      provider: "v8",
      include: ["src/engine/**/*.ts", "src/app/**/*.{ts,tsx}"],
      exclude: ["src/engine/types.ts", "src/app/App.tsx"], // type declarations / browser-router bootstrap
      reporter: ["text", "html", "json-summary"],
    },
  },
});
