FROM node:20-alpine
WORKDIR /app/Desktop/orientation-ia/web
ENV NODE_ENV=production
COPY Desktop/orientation-ia/web/package*.json ./
RUN npm ci
COPY Desktop/orientation-ia/web/ ./
RUN npm run build
EXPOSE 3000
CMD ["sh", "-c", "npm run start -- --hostname 0.0.0.0 --port ${PORT:-3000}"]