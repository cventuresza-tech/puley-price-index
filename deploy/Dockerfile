# Puley's daily run of the index on the Skryp server: Python (standard library only) and git.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client curl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /index
CMD ["sh", "deploy/daily-loop.sh"]
