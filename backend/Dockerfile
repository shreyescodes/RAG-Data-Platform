FROM python:3.10-slim

# Create a non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
