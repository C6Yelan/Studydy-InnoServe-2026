import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    proxy: {
      "/v1": {
        target: loadEnv(mode, ".", "STUDYDY_").STUDYDY_BACKEND_ORIGIN ?? "http://127.0.0.1:8002",
        changeOrigin: false,
      },
    },
  },
}));
