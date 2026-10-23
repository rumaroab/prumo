import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({ plugins: [react(), {
  name: "isolated-navigation-fixtures",
  configureServer(server) { server.middlewares.use((request, _response, next) => {
    if (request.headers.accept?.includes("text/html") && /^\/(scenarios(?:[/?]|$)|brief\/)/.test(request.url || "")) request.url = "/tests/navigation.html";
    next();
  }); },
}], server: { host: "127.0.0.1", port: 5174, strictPort: true } });
