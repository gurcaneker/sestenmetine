# ---- build stage --------------------------------------------------------
# Node 22, not 20: @testing-library/jest-dom (test-agent's devDependency)
# declares engines.node >= 22 and `yarn install` hard-fails on Node 20 even
# though the actual `yarn build` below never touches it.
FROM node:22-alpine AS build
WORKDIR /app

# node:22-alpine ships Yarn Classic 1.22.22 preinstalled — matches
# package.json's `packageManager: yarn@1.22.22` pin exactly, so no corepack
# step needed (corepack would try to fetch it from the network at build
# time, which fails in network-restricted build environments).

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile

COPY . .

# IMPORTANT: CRA/craco embed REACT_APP_* variables into the compiled JS
# bundle AT BUILD TIME (`yarn build` below) — NOT read at container runtime.
# Setting these as `environment:` on the running container would do nothing;
# they must be passed as --build-arg at `docker compose build` time (see
# docker-compose.yml `frontend.build.args`, sourced from the root .env).
# Changing either value requires rebuilding this image (docker compose build
# frontend --no-cache), not just restarting the container.
# Docker lint (SecretsUsedInArgOrEnv) flags REACT_APP_API_KEY as ARG/ENV —
# expected and fine here: it is NOT a real secret (see README.md /
# SECURITY_NOTES.md), it ends up in the public JS bundle either way.
ARG REACT_APP_BACKEND_URL=""
ARG REACT_APP_API_KEY=""
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL
ENV REACT_APP_API_KEY=$REACT_APP_API_KEY

RUN yarn build

# ---- serve stage ---------------------------------------------------------
FROM nginx:1.27-alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
