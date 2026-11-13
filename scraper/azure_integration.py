"""
azure_integration.py
Microsoft Azure Key Vault & Azure Blob Storage Integration
for Walmart Production Scraper
Commit: d32df9e2a47dc2beb9ce4a03c16249342e92b5e4 (HEAD -> main, revision d32df9e-rev2)
"""

import json
import logging
import os
from typing import Any, Dict, Optional

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
    Returns True if Key Vault secrets were queried and applied, False otherwise.
    """
    kv_url = getattr(settings, "azure_key_vault_url", "") or ""
    if not kv_url:
        return False

    if getattr(settings, "proxy_server", "") and getattr(settings, "proxy_username", "") and getattr(settings, "proxy_password", ""):
        return False

    if not AZURE_SDK_AVAILABLE or DefaultAzureCredential is None or SecretClient is None:
        logger.warning("[AZURE KEY VAULT] azure-identity / azure-keyvault-secrets not installed; skipping Key Vault lookup.")
        return False

    try:
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=kv_url, credential=credential)
        updated = False

        if not getattr(settings, "proxy_server", ""):
            settings.proxy_server = client.get_secret("PROXY-SERVER").value or ""
            updated = True
        if not getattr(settings, "proxy_username", ""):
            settings.proxy_username = client.get_secret("PROXY-USERNAME").value or ""
            updated = True
        if not getattr(settings, "proxy_password", ""):
            settings.proxy_password = client.get_secret("PROXY-PASSWORD").value or ""
            updated = True

        if updated:
            logger.info(f"[AZURE KEY VAULT] Hydrated proxy credentials from {kv_url}")
        return updated
    except Exception as ex:
        logger.error(f"[AZURE KEY VAULT ERROR] Could not fetch proxy secrets from {kv_url}: {ex}")
        return False


class AzureBlobPublisher:
    """
    Publishes committed release packages to Azure Blob Storage ONLY AFTER local
    publication gates approve promotion.
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

        if not products_file or not os.path.exists(products_file):
            return {"uploaded": False, "reason": f"Committed products file missing: {products_file}"}
        if not evidence_file or not os.path.exists(evidence_file):
            return {"uploaded": False, "reason": f"Committed evidence file missing: {evidence_file}"}

        try:
            container_client = client.get_container_client(self.container_name)
            try:
                container_client.create_container()
            except Exception:
                pass  # Container may already exist

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
                f"'{self.container_name}' ({pointer_blob})"
            )
            return {
                "uploaded": True,
                "container": self.container_name,
                "release_id": release_id,
                "pointer_blob": pointer_blob,
                "products_blob": prod_blob_rel,
                "evidence_blob": evid_blob_rel,
            }
        except Exception as ex:
            logger.error(f"[AZURE BLOB ERROR] Failed publishing release {release_id}: {ex}")
            return {"uploaded": False, "reason": str(ex)}
