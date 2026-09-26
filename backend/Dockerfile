FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

RUN chmod +x docker/entrypoint.sh

ENV NODE_ENV=production
EXPOSE 3100

ENTRYPOINT ["docker/entrypoint.sh"]
