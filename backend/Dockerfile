FROM nvidia/cuda:12.5.1-devel-ubuntu22.04

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    python3-pip python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY src ./src

CMD ["uvicorn", "usd_studio.main:app", "--host", "0.0.0.0", "--port", "8000"]
