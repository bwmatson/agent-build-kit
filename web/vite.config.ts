import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build lands inside the Python package, where `abk serve` finds it and the
// wheel ships it.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../src/agent_build_kit/serve/static",
    emptyOutDir: true,
  },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
