FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ARG DEBIAN_FRONTEND=noninteractive
ARG USERNAME=vscode
ARG PROJECT_NAME=starter
ENV TZ=Etc/UTC

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    sudo \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/home/${USERNAME}/.local/bin/:$PATH"
ENV UV_CACHE_DIR=/home/${USERNAME}/.cache/uv
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PATH="/workspaces/${PROJECT_NAME}/.venv/bin:$PATH"

ENTRYPOINT []

ARG USER_UID=1001
ARG USER_GID=1001
RUN groupadd -g ${USER_GID} ${USERNAME} \
    && useradd -m -u ${USER_UID} -g ${USER_GID} -s /bin/bash ${USERNAME} \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
WORKDIR /workspaces/${PROJECT_NAME}
USER ${USERNAME}
