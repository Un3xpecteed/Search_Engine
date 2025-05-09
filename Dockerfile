# VS_Project/Dockerfile (НОВЫЙ ПОДХОД К СТРУКТУРЕ - без комментов на COPY)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_SYSTEM_PYTHON=1 

RUN pip install --no-cache-dir uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

COPY requirements.txt ./ 
RUN echo ">>> Syncing environment from requirements.txt using uv pip sync..." && \
    uv pip sync --no-cache requirements.txt && \
    echo ">>> Environment synced successfully."

COPY app/ ./app/
COPY alembic/. ./alembic/
COPY alembic.ini .

RUN echo "--- Contents of /code ---" && ls -la
RUN echo "--- Contents of /code/app ---" && ls -la ./app
RUN echo "--- Contents of /code/alembic ---" && ls -la ./alembic

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]