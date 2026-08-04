# Agent service: LangGraph RCA + change-stream watcher + FastAPI/SSE.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# deps first for layer caching
COPY pyproject.toml /app/pyproject.toml
COPY nova_agent /app/nova_agent
RUN pip install -e .

EXPOSE 8000
CMD ["python", "-m", "nova_agent"]
