# Multi-stage: frontend-react needs an actual build step (Vite/JSX
# aren't servable as-is, unlike frontend/'s plain HTML/CSS/JS console,
# which is why that one just bind-mounts source into nginx directly).
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# VITE_* build-time env vars (Firebase config) are baked in at build
# time, not runtime -- Vite inlines import.meta.env.VITE_* into the
# bundle during `vite build`. Pass them as build args if this image is
# built with a real Firebase project configured; omitted, the app
# degrades honestly (see lib/firebase.js) rather than failing to build.
ARG VITE_FIREBASE_API_KEY=
ARG VITE_FIREBASE_AUTH_DOMAIN=
ARG VITE_FIREBASE_PROJECT_ID=
ARG VITE_FIREBASE_APP_ID=
ARG VITE_API_BASE_URL=
ENV VITE_FIREBASE_API_KEY=$VITE_FIREBASE_API_KEY
ENV VITE_FIREBASE_AUTH_DOMAIN=$VITE_FIREBASE_AUTH_DOMAIN
ENV VITE_FIREBASE_PROJECT_ID=$VITE_FIREBASE_PROJECT_ID
ENV VITE_FIREBASE_APP_ID=$VITE_FIREBASE_APP_ID
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:alpine
COPY --from=build /frontend-react-dist /usr/share/nginx/html
EXPOSE 80
