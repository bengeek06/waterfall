FROM node:24-alpine AS runtime

WORKDIR /workspace

COPY package.json package-lock.json ./
COPY apps/frontend/package.json apps/frontend/package.json
COPY packages/api-client-ts/package.json packages/api-client-ts/package.json
COPY openapi openapi

RUN npm ci

COPY apps/frontend apps/frontend
COPY packages/api-client-ts packages/api-client-ts

RUN npm run api-client:build && npm --workspace frontend run build

EXPOSE 3000

CMD ["npm", "--workspace", "frontend", "run", "start", "--", "-H", "0.0.0.0", "-p", "3000"]
