FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY reverb ./reverb
COPY scripts ./scripts
COPY config ./config
COPY docs ./docs
COPY evidence ./evidence

RUN python -m pip install --no-cache-dir .

EXPOSE 8000
CMD ["python", "scripts/preview_server.py", "--host", "0.0.0.0", "--port", "8000"]
