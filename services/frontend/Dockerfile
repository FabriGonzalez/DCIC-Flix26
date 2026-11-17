# Contexto de build: services/frontend (no usa el helper de Python, D4).

# Etapa 1: compila la app (chequeo de tipos + build de Vite).
FROM node:26-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Etapa 2: solo nginx y el resultado del build. Node no llega a la imagen final.
FROM nginx:1.30-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
