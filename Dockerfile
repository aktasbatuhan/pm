FROM python:3.12-slim

WORKDIR /app

# System deps + gh CLI
RUN apt-get update && apt-get install -y --no-install-recommends git curl && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Source (web/ excluded via .dockerignore)
COPY . .

RUN mkdir -p /data/dash-pm

ENV HERMES_HOME=/data/dash-pm
ENV KAI_HOME=/data/dash-pm
ENV PYTHONUNBUFFERED=1

# Railway sets PORT dynamically, server.py reads it
CMD ["python", "server.py"]
