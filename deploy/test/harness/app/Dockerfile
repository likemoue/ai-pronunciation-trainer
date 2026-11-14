FROM python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
COPY app.py health.py HEALTH build-id /srv/
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA} WARMUP=2 STOP_DELAY=3
HEALTHCHECK --interval=1s --timeout=2s --start-period=0s --retries=10 CMD ["python", "/srv/health.py"]
CMD ["python", "/srv/app.py"]
