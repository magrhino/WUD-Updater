import { defineConfig, type PluginOption } from "vite";
import vue from "@vitejs/plugin-vue";
import vueDevTools from "vite-plugin-vue-devtools";

export default defineConfig(({ command }) => {
  const plugins: PluginOption[] = [vue()];
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
          target: "http://127.0.0.1:8080",
          changeOrigin: true,
        },
      },
    },
    build: {
      chunkSizeWarningLimit: 700,
    },
  };
});
