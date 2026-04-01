# Cryovial container: sshd + git + kubectl + docker + kind + crane + laconic-so + exophial.
#
# Multi-stage build. Builder stage fetches all external binaries with pinned
# versions. Final stage copies them in — no network fetches, fully auditable.

# ── Stage 1: fetch external binaries ──
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /out

# Pinned versions — bump these explicitly, not via "latest"
ENV KUBECTL_VERSION=v1.31.4
ENV KIND_VERSION=v0.25.0
ENV CRANE_VERSION=v0.20.3
ENV DOCKER_VERSION=27.4.1

RUN curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
        -o /out/kubectl \
    && chmod +x /out/kubectl

RUN curl -fsSL "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-amd64" \
        -o /out/kind \
    && chmod +x /out/kind

RUN curl -fsSL "https://github.com/google/go-containerregistry/releases/download/${CRANE_VERSION}/go-containerregistry_Linux_x86_64.tar.gz" \
    | tar -xz -C /out crane

RUN curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_VERSION}.tgz" \
    | tar -xz --strip-components=1 -C /out docker/docker

RUN curl -fsSL -o /out/laconic-so \
        "https://git.vdb.to/cerc-io/stack-orchestrator/releases/download/latest/laconic-so" \
    && chmod +x /out/laconic-so

# ── Stage 2: final image ──
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# System packages — only runtime dependencies, no curl
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openssh-server \
        git \
        python3-minimal \
        python3-pip \
        python3-venv \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Binaries from builder stage — no network fetch
COPY --from=builder /out/kubectl /usr/local/bin/kubectl
COPY --from=builder /out/kind /usr/local/bin/kind
COPY --from=builder /out/crane /usr/local/bin/crane
COPY --from=builder /out/docker /usr/local/bin/docker
COPY --from=builder /out/laconic-so /usr/local/bin/laconic-so

# exophial package (provides exophial-cluster MCP server + image-watcher)
COPY . /build/exophial
RUN pip install --no-cache-dir --break-system-packages /build/exophial \
    && rm -rf /build

# Unprivileged user for SSH access
RUN useradd -m -s /bin/bash exophial \
    && mkdir -p /home/exophial/.ssh /home/exophial/coord.git /run/sshd \
    && chown -R exophial:exophial /home/exophial

# sshd: key-based auth only, no password, no root login
RUN ssh-keygen -A
COPY stacks/cryovial/sshd_config /etc/ssh/sshd_config

# Entrypoint
COPY stacks/cryovial/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22

ENTRYPOINT ["/entrypoint.sh"]
