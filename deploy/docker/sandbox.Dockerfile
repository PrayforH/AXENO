FROM node:22.17.0-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.206
ARG NPM_CONFIG_REGISTRY=https://registry.npmmirror.com

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates tar \
    && npm install --global --registry="${NPM_CONFIG_REGISTRY}" \
      "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /workspace /tmp \
    && chown -R node:node /workspace /tmp

USER 1000:1000
WORKDIR /workspace
ENTRYPOINT ["sleep", "infinity"]
