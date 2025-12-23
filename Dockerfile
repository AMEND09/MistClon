# Use an official lightweight Python image
FROM python:3.11-slim

# Set a working directory
WORKDIR /app

# Install build-time dependencies then clean cache (keeps image small)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy just the server file; keep repo small in image
COPY parser_server.py /app/parser_server.py

# Use non-root user for safety
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

# Expose port
EXPOSE 5000

# Use gunicorn to run the Flask app in production
ENV FLASK_APP=parser_server.py
CMD ["gunicorn", "-b", "0.0.0.0:5000", "parser_server:app", "--workers", "2", "--threads", "4"]
