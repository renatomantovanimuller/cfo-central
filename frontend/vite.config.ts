import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// `vite build --mode demo` gera a vitrine estática (dados fictícios gravados, sem servidor): ver src/demo.ts
export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === "demo" ? [demoHtml()] : [])],
  base: mode === "demo" ? "./" : "/",
  define: { "import.meta.env.VITE_DEMO": JSON.stringify(mode === "demo" ? "1" : "") },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8060" } },
  test: { environment: "node" },
  build: { outDir: mode === "demo" ? "dist-demo" : "dist", chunkSizeWarningLimit: 1600 },
}));

/** Na vitrine não há conexão com bancos: tira o widget da Pluggy do HTML. */
function demoHtml() {
  return {
    name: "cfo-demo-html",
    transformIndexHtml: (html: string) => html.replace(/\s*<script src="https:\/\/cdn\.pluggy\.ai[^>]*><\/script>/, ""),
  };
}
