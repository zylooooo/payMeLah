FROM python:3.13-slim

WORKDIR /app

# Create a non-root user
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app

COPY src/requirements.txt /app/requirements.txt
COPY src/ /app/

RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/logs && chown -R botuser:botuser /app/logs

USER botuser

CMD ["python", "main.py"]