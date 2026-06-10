import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: "jsdom",
    environmentOptions: {
      jsdom: {
        url: "http://127.0.0.1/",
      },
    },
    include: ["tests/**/*.test.ts"],
    setupFiles: ["tests/setup.ts"],
    clearMocks: true,
    restoreMocks: true,
    mockReset: true,
    isolate: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "cobertura", "lcov"],
      reportsDirectory: "coverage",
      include: ["src/**/*.ts", "src/**/*.vue"],
    },
  },
});
