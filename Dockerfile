# Admin Panel Dockerfile - Vite React TypeScript Application
# Multi-stage build for optimized production image

# Stage 1: Build stage
FROM node:20-alpine AS builder

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./
COPY bun.lockb* ./

# Install dependencies (using npm for broader compatibility)
RUN npm ci --legacy-peer-deps

# Copy source code
COPY . .

# Build the application
# The admin panel signs staff in with email + password and Google (existing
# staff accounts only) — same @react-oauth/google package as the storefront.
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
ARG VITE_GOOGLE_CLIENT_ID
ENV VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID}

RUN npm run build

# Stage 2: Production stage with Nginx
FROM nginx:alpine AS production

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Runtime config generator (nginx:alpine runs /docker-entrypoint.d/*.sh on start).
# Lets the API URL be set via the API_URL env var without rebuilding the image.
COPY docker-entrypoint.d/40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
# Strip any CR first: a script checked out on Windows with CRLF endings fails to
# launch ("not found", exit 127) and the container restart-loops.
RUN sed -i 's/\r$//' /docker-entrypoint.d/40-runtime-config.sh \
    && chmod +x /docker-entrypoint.d/40-runtime-config.sh

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Create non-root user
RUN adduser -D -u 1001 appuser \
    && chown -R appuser:appuser /usr/share/nginx/html \
    && chown -R appuser:appuser /var/cache/nginx \
    && chown -R appuser:appuser /var/log/nginx \
    && touch /var/run/nginx.pid \
    && chown -R appuser:appuser /var/run/nginx.pid

# Expose port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost/ || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
