# The harness container: bash, git, curl, python3 and the docker CLI. It drives the
# real deploy.sh against the host's docker daemon through /var/run/docker.sock.
FROM python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
RUN apt-get update \
    && apt-get install -y --no-install-recommends git procps curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=docker:29.9.3-cli@sha256:5a7af0dcb0e46c803efe9b45371dd21cb500e5b4453250394ac6f06d49b6e6f1 \
     /usr/local/bin/docker /usr/local/bin/docker
RUN git config --global user.name harness && git config --global user.email harness@example.invalid \
    && git config --global init.defaultBranch main && git config --global advice.detachedHead false
