# Stage 1: build
FROM node:20-alpine AS builder
WORKDIR /app

# Accept Clerk key as build arg — baked into the Angular bundle at compile time
ARG CLERK_PUBLISHABLE_KEY=pk_test_REPLACE_ME

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Inject the key into the production environment file before building
RUN sed -i "s|pk_live_REPLACE_WITH_YOUR_CLERK_KEY|${CLERK_PUBLISHABLE_KEY}|g" \
      src/environments/environment.prod.ts

RUN npm run build -- --configuration production

# Stage 2: serve
FROM nginx:1.27-alpine
COPY --from=builder /app/dist/agr-dashboard/browser /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
