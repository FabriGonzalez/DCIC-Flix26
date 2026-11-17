# Contexto de build: services/frontend (no usa el helper de Python, D4).
#
# Sin `target`, Docker construye la última etapa (nginx). BuildKit solo construye las
# etapas que esa necesita: `dev` queda afuera del `docker compose up` normal.

# Dependencias, compartidas por el build y el modo desarrollo.
FROM node:26-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Modo desarrollo (perfil `dev`, D5): Vite con el código montado desde el host.
# Solo la usa frontend-dev, con `target: dev`. El código no se copia: llega por el montaje.
FROM deps AS dev
CMD ["npm", "run", "dev"]

# Etapa 1: compila la app (chequeo de tipos + build de Vite).
FROM deps AS build
COPY . .
RUN npm run build

# Etapa 2: solo nginx y el resultado del build. Node no llega a la imagen final.
FROM nginx:1.30-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
