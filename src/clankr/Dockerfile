FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl jq python3 python3-venv ripgrep fd-find openssh-client \
    && rm -rf /var/lib/apt/lists/*

# gh CLI (latest from GitHub releases)
RUN ARCH=$(dpkg --print-architecture) \
    && curl -fsSL "https://github.com/cli/cli/releases/latest/download/gh_$(curl -fsSL https://api.github.com/repos/cli/cli/releases/latest | jq -r .tag_name | sed 's/^v//')_linux_${ARCH}.tar.gz" \
    | tar -xz --strip-components=1 -C /usr/local

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN npm install -g @anthropic-ai/claude-code

RUN git config --system user.name "clankr-agent" \
    && git config --system user.email "clankr-agent@noreply" \
    && git config --system credential.helper '!f() { echo "username=x-access-token"; echo "password=$GH_TOKEN"; }; f'

RUN usermod -d /home/agent -l agent node && mv /home/node /home/agent
USER agent
WORKDIR /work
ENV HOME=/home/agent
ENV CLAUDE_CONFIG_DIR=/home/agent/.claude

ENTRYPOINT ["claude", "--dangerously-skip-permissions"]
