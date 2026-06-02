import { defineConfig, loadEnv, type PluginOption } from "vite";
import vue from "@vitejs/plugin-vue";
import vueDevTools from "vite-plugin-vue-devtools";

export default defineConfig(({ command, mode, isPreview }) => {
  const plugins: PluginOption[] = [vue()];
  const devEnv = loadEnv(mode, ".", "WUD_WEB_DEV_");
  const viteEnv = loadEnv(mode, ".", "VITE_");
  const backendPort = devEnv.WUD_WEB_DEV_BACKEND_PORT ?? "8080";
  const demoMode = mode === "demo" || viteEnv.VITE_WUD_DEMO_MODE === "true";
  if (command === "serve") {
    plugins.push(vueDevTools());
  }

  return {
    base:
      (command === "build" || isPreview) && demoMode
        ? (viteEnv.VITE_WUD_PAGES_BASE ?? "/WUD-Updater/")
        : "/",
    plugins,
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: `http://127.0.0.1:${backendPort}`,
          changeOrigin: true,
        },
      },
    },
    build: {
      chunkSizeWarningLimit: 700,
      rolldownOptions: {
        onLog(level, log, defaultHandler) {
          const source = log.id ?? log.loc?.file ?? "";
          if (
            level === "warn" &&
            log.code === "INVALID_ANNOTATION" &&
            /@vueuse[\\/]core[\\/]dist[\\/]index\.js/.test(source)
          ) {
            return;
          }
          defaultHandler(level, log);
        },
        output: {
          codeSplitting: {
            groups: [
              {
                name: "vue-runtime",
                test:
                  /node_modules[\\/](?:@vue|@vueuse|pinia|vue|vue-router)[\\/]/,
                priority: 20,
              },
              {
                name: "icons",
                test: /node_modules[\\/]@lucide[\\/]vue[\\/]/,
                priority: 15,
              },
            ],
          },
        },
      },
    },
  };
});
