import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En producción, nginx sirve el build y reenvía /api al backend (nginx.conf).
// El modo desarrollo (perfil `dev`, D5) se agrega en F7.
export default defineConfig({
  plugins: [react()],
});
