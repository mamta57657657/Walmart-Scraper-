"""
azure_integration.py
Microsoft Azure Key Vault & Azure Blob Storage Integration
for Walmart Production Scraper
Commit: d32df9e2a47dc2beb9ce4a03c16249342e92b5e4 (HEAD -> main, revision d32df9e-rev2)
"""

import glob
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AzureIntegration")

try:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
    from azure.storage.blob import BlobServiceClient
    AZURE_SDK_AVAILABLE = True
except ImportError:
    DefaultAzureCredential = None  # type: ignore
    SecretClient = None  # type: ignore
    BlobServiceClient = None  # type: ignore
    AZURE_SDK_AVAILABLE = False


def resolve_key_vault_proxy_secrets(settings: Any) -> bool:
    """
    Hydrates proxy credentials from Azure Key Vault when AZURE_KEY_VAULT_URL is configured
    and explicit proxy environment variables are not already populated.
    Matches secret names in scraper/azure_deployment.md:
      - PROXY-SERVER
      - PROXY-USERNAME
      - PROXY-PASSWORD
    Fails closed by recording settings.key_vault_lookup_error and returning False if any
    configured Key Vault lookup fails or yields incomplete proxy credentials.
    """
    kv_url = str(getattr(settings, "azure_key_vault_url", "") or "").strip()
    if not kv_url:
        return False

    has_all_explicit = bool(
        str(getattr(settings, "proxy_server", "") or "").strip()
        and str(getattr(settings, "proxy_username", "") or "").strip()
        and str(getattr(settings, "proxy_password", "") or "").strip()
    )
    if has_all_explicit:
        if hasattr(settings, "key_vault_lookup_error"):
            settings.key_vault_lookup_error = ""
        return True

    if not AZURE_SDK_AVAILABLE or DefaultAzureCredential is None or SecretClient is None:
        reason = "azure-identity / azure-keyvault-secrets not installed while AZURE_KEY_VAULT_URL is configured."
        if hasattr(settings, "key_vault_lookup_error"):
            settings.key_vault_lookup_error = reason
        logger.error(f"[AZURE KEY VAULT ERROR] {reason}")
        return False

    try:
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=kv_url, credential=credential)

        if not str(getattr(settings, "proxy_server", "") or "").strip():
            settings.proxy_server = str(client.get_secret("PROXY-SERVER").value or "").strip()
        if not str(getattr(settings, "proxy_username", "") or "").strip():
            settings.proxy_username = str(client.get_secret("PROXY-USERNAME").value or "").strip()
        if not str(getattr(settings, "proxy_password", "") or "").strip():
            settings.proxy_password = str(client.get_secret("PROXY-PASSWORD").value or "").strip()

        if not (settings.proxy_server and settings.proxy_username and settings.proxy_password):
            reason = f"Incomplete proxy credentials resolved from Key Vault {kv_url}"
            if hasattr(settings, "key_vault_lookup_error"):
                settings.key_vault_lookup_error = reason
            logger.error(f"[AZURE KEY VAULT ERROR] {reason}")
            return False

        if hasattr(settings, "key_vault_lookup_error"):
            settings.key_vault_lookup_error = ""
        logger.info(f"[AZURE KEY VAULT] Hydrated proxy credentials from {kv_url}")
        return True
    except Exception as ex:
        reason = f"Could not fetch proxy secrets from {kv_url}: {ex}"
        if hasattr(settings, "key_vault_lookup_error"):
            settings.key_vault_lookup_error = reason
        logger.error(f"[AZURE KEY VAULT ERROR] {reason}")
        return False


def ensure_proxy_credentials_ready(settings: Any) -> Tuple[bool, str]:
    """
    Validates proxy credential resolution with strict fail-closed semantics:
    if AZURE_KEY_VAULT_URL is configured, lookup MUST succeed cleanly before launching browser.
    """
    kv_url = str(getattr(settings, "azure_key_vault_url", "") or "").strip()
    if not kv_url:
        return True, "No Key Vault configured"

    ok = resolve_key_vault_proxy_secrets(settings)
    if not ok:
        reason = str(getattr(settings, "key_vault_lookup_error", "") or f"Key Vault lookup failed for {kv_url}")
        return False, reason
    return True, "Azure Key Vault proxy credentials verified"


class AzureBlobPublisher:
    """
    Publishes committed release packages & durable Container App Job state to Azure Blob Storage.
    Upload order preserves prior committed deliveries on any failure:
      1. Upload immutable release artifacts under releases/{release_id}/...
      2. Upload canonical store/date JSON & raw evidence blobs
      3. Upload committed manifest pointer output/publication_manifest_{store}.json LAST
    """

    def __init__(
        self,
        connection_string: str = "",
        account_url: str = "",
        container_name: str = "walmart-scraper-data",
        blob_service_client: Optional[Any] = None,
    ):
        self.connection_string = connection_string
        self.account_url = account_url
        self.container_name = container_name or "walmart-scraper-data"
        self._injected_client = blob_service_client

    def is_configured(self) -> bool:
        return bool(self._injected_client or self.connection_string or self.account_url)

    def _get_service_client(self) -> Optional[Any]:
        if self._injected_client is not None:
            return self._injected_client
        if not AZURE_SDK_AVAILABLE or BlobServiceClient is None:
            return None
        if self.connection_string:
            return BlobServiceClient.from_connection_string(self.connection_string)
        if self.account_url and DefaultAzureCredential is not None:
            return BlobServiceClient(account_url=self.account_url, credential=DefaultAzureCredential())
        return None

    def sync_durable_state_down(self, store_number: str, staging_dir: str, output_dir: str) -> Dict[str, Any]:
        """
        Hydrates durable checkpoint, staging records, raw evidence, master assortment, and manifest
        from Azure Blob Storage (`state/{store_number}/...`) into local working directories at startup
        so ephemeral scheduled Azure Container App Jobs resume seamlessly across runs.
        """
        if not self.is_configured():
            return {"synced": False, "reason": "Azure Storage not configured", "downloaded": []}
        client = self._get_service_client()
        if client is None:
            return {"synced": False, "reason": "azure-storage-blob SDK unavailable", "downloaded": []}

        downloaded: List[str] = []
        prefix = f"state/{store_number}/"
        try:
            container_client = client.get_container_client(self.container_name)
            if not hasattr(container_client, "list_blobs") or not hasattr(container_client, "download_blob"):
                return {"synced": False, "reason": "Blob client does not support state listing/download", "downloaded": []}

            os.makedirs(staging_dir, exist_ok=True)
            os.makedirs(output_dir, exist_ok=True)

            for blob_item in container_client.list_blobs(name_starts_with=prefix):
                blob_name = blob_item.name if hasattr(blob_item, "name") else str(blob_item)
                rel = blob_name[len(prefix):]
                if rel.startswith("staging/"):
                    dest_path = os.path.join(staging_dir, os.path.basename(rel))
                elif rel.startswith("output/"):
                    dest_path = os.path.join(output_dir, os.path.basename(rel))
                else:
                    continue

                if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                    continue

                downloader = container_client.download_blob(blob_name)
                data = downloader.readall() if hasattr(downloader, "readall") else downloader.content_as_bytes()
                tmp_path = f"{dest_path}.tmp"
                with open(tmp_path, "wb") as f:
                    f.write(data)
                os.replace(tmp_path, dest_path)
                downloaded.append(blob_name)

            if downloaded:
                logger.info(f"[AZURE DURABLE STATE DOWN] Restored {len(downloaded)} state file(s) for Store #{store_number}")
            return {"synced": True, "downloaded": downloaded}
        except Exception as ex:
            logger.warning(f"[AZURE DURABLE STATE DOWN] Could not restore state for Store #{store_number}: {ex}")
            return {"synced": False, "reason": str(ex), "downloaded": downloaded}

    def sync_durable_state_up(self, store_number: str, staging_dir: str, output_dir: str) -> Dict[str, Any]:
        """
        Persists local checkpoint, staging records, raw evidence, master assortment, and manifest
        to Azure Blob Storage (`state/{store_number}/...`) so interrupted or budget-stopped scheduled
        Container App Jobs preserve full state for the next scheduled invocation.
        """
        if not self.is_configured():
            return {"synced": False, "reason": "Azure Storage not configured", "uploaded": []}
        client = self._get_service_client()
        if client is None:
            return {"synced": False, "reason": "azure-storage-blob SDK unavailable", "uploaded": []}

        uploaded: List[str] = []
        try:
            container_client = client.get_container_client(self.container_name)
            try:
                container_client.create_container()
            except Exception:
                pass

            candidates: List[Tuple[str, str]] = []
            for pat in (
                os.path.join(staging_dir, f"checkpoint_{store_number}_*.json"),
                os.path.join(staging_dir, f"staging_records_{store_number}_*.json"),
                os.path.join(staging_dir, f"raw_evidence_{store_number}_*.jsonl"),
            ):
                for fp in sorted(glob.glob(pat)):
                    candidates.append((fp, f"state/{store_number}/staging/{os.path.basename(fp)}"))

            for pat in (
                os.path.join(output_dir, f"master_store_assortment_{store_number}.json"),
                os.path.join(output_dir, f"publication_manifest_{store_number}.json"),
            ):
                if os.path.exists(pat):
                    candidates.append((pat, f"state/{store_number}/output/{os.path.basename(pat)}"))

            for local_path, blob_name in candidates:
                with open(local_path, "rb") as f:
                    container_client.upload_blob(name=blob_name, data=f.read(), overwrite=True)
                uploaded.append(blob_name)

            if uploaded:
                logger.info(f"[AZURE DURABLE STATE UP] Persisted {len(uploaded)} durable state blob(s) for Store #{store_number}")
            return {"synced": True, "uploaded": uploaded}
        except Exception as ex:
            logger.error(f"[AZURE DURABLE STATE UP ERROR] Failed syncing state for Store #{store_number}: {ex}")
            return {"synced": False, "reason": str(ex), "uploaded": uploaded}

    def publish_committed_release(self, manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Uploads a locally COMMITTED release manifest and its immutable products/evidence
        files to Azure Blob Storage.
        Never uploads uncommitted or partial runs.
        """
        if not manifest or manifest.get("status") != "COMMITTED":
            return {"uploaded": False, "reason": "No COMMITTED manifest to publish"}

        if not self.is_configured():
            return {"uploaded": False, "reason": "Azure Storage not configured"}

        client = self._get_service_client()
        if client is None:
            logger.warning("[AZURE BLOB] azure-storage-blob SDK unavailable; skipping remote upload.")
            return {"uploaded": False, "reason": "azure-storage-blob SDK unavailable"}

        products_file = manifest.get("products_file", "")
        evidence_file = manifest.get("evidence_file", "")
        release_id = manifest.get("release_id", "")
        store_number = manifest.get("store_number", "")
        crawl_date = manifest.get("crawl_date", "")
        run_id = manifest.get("run_id", "")

        if not products_file or not os.path.exists(products_file):
            return {"uploaded": False, "reason": f"Committed products file missing: {products_file}"}
        if not evidence_file or not os.path.exists(evidence_file):
            return {"uploaded": False, "reason": f"Committed evidence file missing: {evidence_file}"}

        try:
            container_client = client.get_container_client(self.container_name)
            try:
                container_client.create_container()
            except Exception:
                pass

            prod_blob_rel = f"releases/{release_id}/walmart_{store_number}_{crawl_date}.json"
            evid_blob_rel = f"releases/{release_id}/raw_evidence_{store_number}_{crawl_date}.jsonl"
            rel_manifest_blob = f"releases/{release_id}/manifest.json"
            canonical_prod_blob = f"output/walmart_{store_number}_{crawl_date}.json"
            canonical_evid_blob = f"output/raw_evidence_{store_number}_{crawl_date}.jsonl"
            pointer_blob = f"output/publication_manifest_{store_number}.json"

            with open(products_file, "rb") as f:
                prod_bytes = f.read()
            with open(evidence_file, "rb") as f:
                evid_bytes = f.read()

            remote_manifest = dict(manifest)
            remote_manifest["azure_container"] = self.container_name
            remote_manifest["azure_products_blob"] = prod_blob_rel
            remote_manifest["azure_evidence_blob"] = evid_blob_rel
            manifest_bytes = json.dumps(remote_manifest, indent=2).encode("utf-8")

            # 1. Immutable release package blobs first
            container_client.upload_blob(name=prod_blob_rel, data=prod_bytes, overwrite=True)
            container_client.upload_blob(name=evid_blob_rel, data=evid_bytes, overwrite=True)
            container_client.upload_blob(name=rel_manifest_blob, data=manifest_bytes, overwrite=True)

            # 2. Canonical dated copies
            container_client.upload_blob(name=canonical_prod_blob, data=prod_bytes, overwrite=True)
            container_client.upload_blob(name=canonical_evid_blob, data=evid_bytes, overwrite=True)

            # 3. Committed manifest pointer LAST
            container_client.upload_blob(name=pointer_blob, data=manifest_bytes, overwrite=True)

            logger.info(
                f"[AZURE BLOB PUBLISHED] Release {release_id} uploaded to container "
                f"'{self.container_name}' ({pointer_blob}) "
                f"[store_number={store_number}, run_id={run_id or 'unspecified'}]"
            )
            return {
                "uploaded": True,
                "container": self.container_name,
                "release_id": release_id,
                "store_number": store_number,
                "run_id": run_id,
                "pointer_blob": pointer_blob,
                "products_blob": prod_blob_rel,
                "evidence_blob": evid_blob_rel,
            }
        except Exception as ex:
            logger.error(f"[AZURE BLOB ERROR] Failed publishing release {release_id}: {ex}")
            return {"uploaded": False, "reason": str(ex)}
