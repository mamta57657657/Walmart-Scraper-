# Walmart Scraper Azure Container Image
# Commit: d32df9e2a47dc2beb9ce4a03c16249342e92b5e4 (HEAD -> main, revision d32df9e-rev2, dated correction checkpoint 2026-11-08)
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code, config and category taxonomy
COPY . .

# Run playwright install for chromium
RUN playwright install chromium

# Default entrypoint for Azure Container Apps / Azure Functions
CMD ["python", "walmart_scraper.py"]
