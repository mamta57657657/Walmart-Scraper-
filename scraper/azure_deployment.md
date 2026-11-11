# Microsoft Azure Deployment & Operating Guide: Production Walmart Scraper
**Commit:** `d32df9e2a47dc2beb9ce4a03c16249342e92b5e4` (HEAD -> main, revision `d32df9e-rev2`, dated correction checkpoint `2026-11-08`)

This guide provides end-to-end instructions for deploying, scheduling, and operating the Production Walmart Scraper in Microsoft Azure.

---

## 1. Architecture Overview
- **Compute**: Azure Container App (Job) or Azure VM running Python 3.11 + Playwright headless Chromium.
- **Scheduler**: Azure Logic Apps or Azure Container Apps Job Schedule (`0 2 * * 2,5` for Tuesday and Friday at 02:00 UTC).
- **Secrets & Credentials**: Azure Key Vault storing residential proxy credentials, Azure Storage keys, and notification webhooks.
- **Storage**: Azure Blob Storage (Container: `walmart-scraper-data`), with immutable versioning and atomic writes.
- **Monitoring**: Azure Application Insights for runtime telemetry, error rates, and canary validation alerts.

---

## 2. Prerequisites
1. Azure CLI installed (`az login`)
2. Resource Group created: `rg-walmart-scraper`
3. Azure Storage Account: `stwalmartscraper`
4. Azure Key Vault: `kv-walmart-scraper`

---

## 3. Step-by-Step Deployment

### Step A: Provision Storage & Key Vault
```bash
# Create Resource Group
az group create --name rg-walmart-scraper --location eastus

# Create Storage Account and Blob Container
az storage account create --name stwalmartscraper --resource-group rg-walmart-scraper --location eastus --sku Standard_LRS
az storage container create --account-name stwalmartscraper --name walmart-scraper-data

# Create Key Vault and Store Secrets
az keyvault create --name kv-walmart-scraper --resource-group rg-walmart-scraper --location eastus
az keyvault secret set --vault-name kv-walmart-scraper --name "PROXY-SERVER" --value "http://pr.oxylabs.io:7777"
az keyvault secret set --vault-name kv-walmart-scraper --name "PROXY-USERNAME" --value "customer-username"
az keyvault secret set --vault-name kv-walmart-scraper --name "PROXY-PASSWORD" --value "customer-password"
```

### Step B: Build and Push Docker Image to Azure Container Registry (ACR)
```bash
# Create ACR
az acr create --resource-group rg-walmart-scraper --name acrwalmartscraper --sku Basic --admin-enabled true

# Build and push container
cd scraper
az acr build --registry acrwalmartscraper --image walmart-scraper:v1 .
```

### Step C: Deploy as Azure Container App Scheduled Job (Twice Weekly)
```bash
# Create Azure Container Apps Environment
az containerapp env create --name env-walmart-scraper --resource-group rg-walmart-scraper --location eastus

# Deploy Scheduled Job (Runs Tuesday & Friday at 2:00 AM UTC)
az containerapp job create \
  --name job-walmart-scraper \
  --resource-group rg-walmart-scraper \
  --environment env-walmart-scraper \
  --trigger-type Schedule \
  --cron-expression "0 2 * * 2,5" \
  --replica-timeout 7200 \
  --image acrwalmartscraper.azurecr.io/walmart-scraper:v1 \
  --registry-server acrwalmartscraper.azurecr.io \
  --env-vars \
    AZURE_STORAGE_CONTAINER="walmart-scraper-data" \
    CATEGORIES_CSV_PATH="Walmart_Category_URLs.csv"
```

---

## 4. Operational Runbook & Maintenance

### Adding a New Walmart Location
To scrape an additional Walmart store without touching code:
1. Open `config.py` (or inject store list via JSON environment variable `WALMART_STORES_JSON`).
2. Add the store number and ZIP code:
   ```python
   StoreConfig(store_number="1129", zipcode="78701", name="Walmart Supercenter", address="2525 E Anderson Ln, Austin, TX 78752")
   ```
3. The scraper will automatically bind to the new store, inject cookies, lock fulfillment, and output location-tagged JSON.

### Adding or Modifying Categories
1. Open `Walmart_Category_URLs.csv`.
2. Add a new row with category, subcategory, URL, and optional canary UPC:
   ```csv
   Bakery,Fresh Bread,https://www.walmart.com/browse/food/bakery/bread/976759_976785_1001455,078742119902
   ```
3. The scraper reads the CSV dynamically on every execution.

### Interruption Recovery & Atomic Writes
- If an Azure container is terminated or times out mid-run:
  1. The dataset will not pass the 500-record threshold gate.
  2. The atomic writer discards the incomplete `.tmp` file and preserves the prior successful run file (`.bak`).
  3. Azure Container Job retries the execution automatically with a fresh container.
