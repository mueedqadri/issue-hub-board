# Build from the repository root: docker build -f deploy/Dockerfile -t issue-hub-board .
FROM python:3.13.7-alpine3.22
RUN apk add --no-cache git
COPY issue-hub-board /app/issue-hub-board
COPY issue_hub_board /app/issue_hub_board
COPY --chmod=755 deploy/run.sh /usr/local/bin/issue-hub-board-sync
USER 1000:1000
EXPOSE 8788
LABEL org.opencontainers.image.source="https://github.com/mueedqadri/issue-hub-board" \
      org.opencontainers.image.description="A fast, read-only, Linear-style viewer for markdown issue hubs" \
      org.opencontainers.image.licenses="MIT"
ENTRYPOINT ["/usr/local/bin/issue-hub-board-sync"]
