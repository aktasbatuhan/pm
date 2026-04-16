FROM python:3.12-slim

WORKDIR /app

COPY tests/mock_mcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tests/mock_mcp/server.py .
COPY tests/mock_mcp/scenarios/ scenarios/

ENV PORT=8000
EXPOSE 8000

CMD ["python", "server.py"]
