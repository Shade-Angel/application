FROM node:22-alpine AS build
WORKDIR /app
ARG VITE_API_KEY=local-demo-key
ENV VITE_API_KEY=$VITE_API_KEY
COPY package.json package-lock.json tsconfig*.json vite.config.ts index.html ./
RUN npm ci --no-audit
COPY src ./src
COPY public ./public
RUN npm run build
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
