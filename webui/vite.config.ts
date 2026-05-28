import { defineConfig, loadEnv, type PluginOption } from "vite";
import vue from "@vitejs/plugin-vue";
import vueDevTools from "vite-plugin-vue-devtools";

export default defineConfig(({ command, mode }) => {
  const plugins: PluginOption[] = [vue()];
  const env = loadEnv(mode, ".", "WUD_WEB_DEV_");
  const backendPort = env.WUD_WEB_DEV_BACKEND_PORT ?? "8080";
  if (command === "serve") {
    plugins.push(vueDevTools());
  }

  return {
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
    },
  };
});
