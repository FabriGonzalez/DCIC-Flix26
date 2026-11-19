import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// En producción, nginx sirve el build y reenvía /api al backend (nginx.conf).
// Las opciones de `server` solo aplican al modo desarrollo: el servicio frontend-dev
// del perfil `dev` (D5). El build de producción las ignora.
export default defineConfig(({ mode }) => {
  // Variables que pone el compose. loadEnv evita depender de los tipos de Node (process).
  const env = loadEnv(mode, ".", "DEV_");

  return {
    plugins: [react()],
    server: {
      // 0.0.0.0: por defecto Vite escucha solo en el localhost del contenedor.
      host: true,
      port: 5173,
      strictPort: true,
      // Con el código montado desde Windows, los cambios no llegan como eventos
      // (inotify): Vite tiene que revisar los archivos cada tanto.
      watch: env.DEV_USE_POLLING === "true" ? { usePolling: true, interval: 300 } : undefined,
      // Igual que nginx: /api/health llega al backend como /health.
      proxy: {
        "/api": {
          target: "http://backend:8000",
          rewrite: (path) => path.replace(/^\/api/, ""),
        },
      },
    },
  };
});
