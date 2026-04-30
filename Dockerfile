FROM node:20-alpine
WORKDIR /app/web
ENV NODE_ENV=production
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build
EXPOSE 3000
CMD ["sh", "-c", "npm run start -- --hostname 0.0.0.0 --port ${PORT:-3000}"]
