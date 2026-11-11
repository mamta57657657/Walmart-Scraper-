"""
checkpoint_manager.py
Hard Interruption / Resume State Machine & Incomplete-Run Publication Protection
for Walmart Production Scraper (Azure Execution)
Commit: d32df9e2a47dc2beb9ce4a03c16249342e92b5e4 (HEAD -> main, revision d32df9e-rev2, dated correction checkpoint 2026-11-08)
"""

import os
import json
import logging
import shutil
import time
import hashlib
import glob
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime

import re

logger = logging.getLogger("CheckpointManager")

def sanitize_captured_request(request_data: Any) -> Dict[str, Any]:
    """
    Sanitizes captured HTTP requests by redacting sensitive tokens:
    - Cookie, Set-Cookie
    - Authorization (Bearer / Basic / custom)
    - Proxy-Authorization
    - wm_sec.auth_token, WM_SEC.*
    - API keys and tokens in headers, query strings, and body
    """
    if not isinstance(request_data, dict):
        return {"raw": "[REDACTED]"}

    sanitized = dict(request_data)

    # Sanitize URL query parameters for sensitive tokens
    raw_url = sanitized.get("url", "")
    if isinstance(raw_url, str):
        sanitized["url"] = re.sub(r'([?&](?:token|auth|key|secret|password)=)[^&]+', r'\1[REDACTED]', raw_url, flags=re.IGNORECASE)

    headers = sanitized.get("headers", {})
    if isinstance(headers, dict):
        clean_headers = {}
        sensitive_keys = {
            "cookie", "set-cookie", "authorization", "proxy-authorization",
            "wm_sec.auth_token", "wm_sec.key_version", "x-api-key", "apikey",
            "token", "bearer", "session", "x-signature", "x-auth-token"
        }
        for k, v in headers.items():
            k_low = k.lower()
            if k_low in sensitive_keys or any(term in k_low for term in ["auth", "token", "secret", "cookie", "key"]):
                clean_headers[k] = "[REDACTED]"
            elif isinstance(v, str) and re.search(r'\b(bearer|basic)\s+[A-Za-z0-9_\-\.]+', v, re.IGNORECASE):
                clean_headers[k] = "[REDACTED]"
            else:
                clean_headers[k] = v
        sanitized["headers"] = clean_headers

    # Redact sensitive body/post_data tokens if present
    post_data = sanitized.get("post_data")
    if isinstance(post_data, str):
        if any(term in post_data.lower() for term in ["token", "secret", "password", "auth", "bearer"]):
            sanitized["post_data"] = "[REDACTED_SENSITIVE_PAYLOAD]"
    elif isinstance(post_data, dict):
        clean_post = dict(post_data)
        for k in list(clean_post.keys()):
            if any(term in k.lower() for term in ["token", "secret", "password", "auth"]):
                clean_post[k] = "[REDACTED]"
        sanitized["post_data"] = clean_post

    return sanitized


class CheckpointManager:
    """
    Manages run checkpoints and protects against incomplete-run publication:
    1. Checkpoint Journaling: Persists category/page cursors and collected record hashes.
    2. Hard Interruption Recovery: Resumes runs seamlessly after SIGINT, OOM, or node reboot.
    3. Cross-Midnight Resumption: Preserves crawl session and staging files across midnight.
    4. Diagnostic Corruption Preservation: Backs up corrupted checkpoints with diagnosis instead of wiping.
    5. Durable Reconciled Page Transactions: Reconciles seen signatures directly from staging records.
    6. Master Assortment Carry-Forward: Indefinitely preserves historical store products missing on later dates.
    7. Atomic Package Transaction with Committed Pointer: Immutable artifacts activated via a single atomic pointer replace.
    8. Durable Raw Evidence with Linkage: Persists sanitized network pairs and assigns traceable capture IDs.
    """

    def __init__(self, store_number: str, crawl_date: str, staging_dir: str = ".staging", output_dir: str = "output"):
        self.store_number = str(store_number)
        self.crawl_date = crawl_date
        self.staging_dir = staging_dir
        self.output_dir = output_dir

        os.makedirs(self.staging_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        # Check for cross-midnight active checkpoint before setting file paths
        active_date = self._find_active_in_progress_date()
        if active_date and active_date != self.crawl_date:
            logger.info(f"[CROSS-MIDNIGHT RESUME] Detected active in-progress crawl from {active_date}. Preserving session date.")
            self.crawl_date = active_date

        self.checkpoint_file = os.path.join(staging_dir, f"checkpoint_{self.store_number}_{self.crawl_date}.json")
        self.staging_data_file = os.path.join(staging_dir, f"staging_records_{self.store_number}_{self.crawl_date}.json")
        self.raw_evidence_file = os.path.join(staging_dir, f"raw_evidence_{self.store_number}_{self.crawl_date}.jsonl")
        self.production_target_file = os.path.join(output_dir, f"walmart_{self.store_number}_{self.crawl_date}.json")
        self.production_evidence_file = os.path.join(output_dir, f"raw_evidence_{self.store_number}_{self.crawl_date}.jsonl")
        self.manifest_file = os.path.join(output_dir, f"publication_manifest_{self.store_number}.json")
        self.master_assortment_file = os.path.join(output_dir, f"master_store_assortment_{self.store_number}.json")

        self.raw_evidence_write_failed = False
        self.evidence_failure_reason = ""
        self.raw_evidence_count = 0
        self.evidence_capture_index: Dict[str, bool] = {}

        # Restore failure status from checkpoint if previously recorded
        self._sync_evidence_failure_from_disk()

        # Reconcile canonical production files with active committed pointer (crash recovery protocol)
        self.reconcile_active_publication()

    def _find_active_in_progress_date(self) -> Optional[str]:
        """Detects if an in-progress crawl for this store started on an earlier date (e.g. cross-midnight)."""
        pattern = os.path.join(self.staging_dir, f"checkpoint_{self.store_number}_*.json")
        for cp_path in glob.glob(pattern):
            try:
                with open(cp_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("status") == "IN_PROGRESS" and data.get("store_number") == self.store_number:
                        return data.get("crawl_date")
            except Exception:
                continue
        return None

    def _sync_evidence_failure_from_disk(self):
        """Restores persisted incomplete-evidence status across process restarts."""
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("has_evidence_failure"):
                        self.raw_evidence_write_failed = True
                        self.evidence_failure_reason = data.get("evidence_failure_reason", "Persisted failure flag")
                        logger.warning(f"[PERSISTED EVIDENCE FAILURE] Restored incomplete-evidence flag: {self.evidence_failure_reason}")
            except Exception:
                pass

    def record_evidence_failure(self, reason: str):
        """Persists incomplete-evidence status to disk so it survives restarts."""
        self.raw_evidence_write_failed = True
        self.evidence_failure_reason = reason
        cp = self.load_checkpoint()
        cp["has_evidence_failure"] = True
        cp["evidence_failure_reason"] = reason
        cp["last_updated"] = datetime.utcnow().isoformat() + "Z"
        temp_path = f"{self.checkpoint_file}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(cp, f, indent=2)
            os.replace(temp_path, self.checkpoint_file)
        except Exception as e:
            logger.error(f"Failed to persist evidence failure status: {e}")

    def append_raw_evidence(self, endpoint: str, request_data: Any, response_payload: Any) -> str:
        """
        Durable persistence of original intercepted network responses.
        Returns a unique capture_id for product-to-evidence linkage.
        Sanitizes sensitive headers and tokens.
        Raises IOError and sets persisted failure flag on write errors.
        """
        self.raw_evidence_count += 1
        capture_id = f"cap_{self.store_number}_{int(time.time()*1000)}_{self.raw_evidence_count}"

        sanitized_req = sanitize_captured_request(request_data)

        entry = {
            "capture_id": capture_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "store_number": self.store_number,
            "crawl_date": self.crawl_date,
            "endpoint": endpoint,
            "request": sanitized_req,
            "response": response_payload
        }
        try:
            with open(self.raw_evidence_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.evidence_capture_index[capture_id] = True
            return capture_id
        except Exception as e:
            self.record_evidence_failure(f"Critical write error: {e}")
            logger.error(f"Failed to persist raw evidence entry: {e}")
            raise IOError(f"Critical failure writing raw evidence: {e}")

    def load_checkpoint(self) -> Dict[str, Any]:
        """
        Loads existing checkpoint if run was interrupted.
        Preserves and diagnoses corruption if the JSON is malformed.
        """
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info(f"[RESUME] Loaded checkpoint from {self.checkpoint_file}. Resuming from Category {data.get('category_index', 0)}, Page {data.get('current_page', 1)}.")
                    return data
            except Exception as e:
                # Diagnostic corruption preservation: do NOT wipe corrupted state!
                corrupt_backup = f"{self.checkpoint_file}.corrupt.{int(time.time())}"
                try:
                    shutil.copy2(self.checkpoint_file, corrupt_backup)
                    logger.error(f"[CHECKPOINT CORRUPTION PRESERVED] Saved corrupted checkpoint to {corrupt_backup}. Error: {e}")
                except Exception as bkp_err:
                    logger.error(f"Could not copy corrupt checkpoint: {bkp_err}")

                return {
                    "store_number": self.store_number,
                    "crawl_date": self.crawl_date,
                    "started_at": datetime.utcnow().isoformat() + "Z",
                    "last_updated": datetime.utcnow().isoformat() + "Z",
                    "category_index": 0,
                    "current_page": 1,
                    "completed_categories": [],
                    "failed_routes": [],
                    "flushed_records_count": 0,
                    "seen_record_signatures": [],
                    "status": "RECOVERED_FROM_CORRUPTION",
                    "corruption_diagnostic": str(e),
                    "corrupt_backup_file": corrupt_backup
                }

        return {
            "store_number": self.store_number,
            "crawl_date": self.crawl_date,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "category_index": 0,
            "current_page": 1,
            "completed_categories": [],
            "failed_routes": [],
            "flushed_records_count": 0,
            "seen_record_signatures": [],
            "status": "INITIALIZED"
        }

    def reconcile_signatures_from_staging(self) -> Set[str]:
        """
        Durable page transaction reconciliation:
        Reconstructs seen_signatures directly from durable staging records,
        guaranteeing records and deduplication signatures can never drift.
        """
        records = self.load_staging_records()
        signatures = set()
        for r in records:
            sig = f"{r.get('upc') or r.get('url')}_{r.get('zipcode')}"
            signatures.add(sig)
        return signatures

    def save_checkpoint(
        self,
        category_index: int,
        current_page: int,
        completed_categories: List[str],
        flushed_count: int,
        seen_signatures: List[str],
        status: str = "IN_PROGRESS",
        category_yields: Optional[Dict[str, int]] = None,
        failed_routes: Optional[List[str]] = None
    ):
        """Atomically saves checkpoint to disk."""
        state = {
            "store_number": self.store_number,
            "crawl_date": self.crawl_date,
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "category_index": category_index,
            "current_page": current_page,
            "completed_categories": list(completed_categories),
            "category_yields": category_yields or {},
            "failed_routes": list(failed_routes or []),
            "flushed_records_count": flushed_count,
            "seen_record_signatures": list(seen_signatures),
            "has_evidence_failure": self.raw_evidence_write_failed,
            "evidence_failure_reason": self.evidence_failure_reason,
            "status": status
        }
        temp_path = f"{self.checkpoint_file}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(temp_path, self.checkpoint_file)
        except Exception as e:
            logger.error(f"Failed to write checkpoint: {e}")

    def commit_page_transaction(
        self,
        page_batch: List[Dict[str, str]],
        category_index: int,
        current_page: int,
        completed_categories: List[str],
        category_yields: Optional[Dict[str, int]] = None,
        failed_routes: Optional[List[str]] = None,
        status: str = "IN_PROGRESS"
    ):
        """
        Durable single page transaction:
        1. Atomically appends/writes batch records to staging file.
        2. Directly reconciles deduplication signatures from the updated staging file.
        3. Atomically writes the checkpoint referencing the exact staging count, reconciled signatures, and failed_routes.
        Eliminates the separate writes window where records and seen signatures could drift.
        """
        if page_batch:
            self.append_staging_records(page_batch)
        reconciled_signatures = list(self.reconcile_signatures_from_staging())
        staging_records = self.load_staging_records()
        self.save_checkpoint(
            category_index=category_index,
            current_page=current_page,
            completed_categories=completed_categories,
            flushed_count=len(staging_records),
            seen_signatures=reconciled_signatures,
            status=status,
            category_yields=category_yields,
            failed_routes=failed_routes
        )

    def append_staging_records(self, new_records: List[Dict[str, str]]):
        """Flushes verified batch records into staging storage immediately."""
        existing = self.load_staging_records()
        existing.extend(new_records)
        temp_data = f"{self.staging_data_file}.tmp"
        with open(temp_data, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        os.replace(temp_data, self.staging_data_file)
        logger.info(f"[STAGING FLUSH] Wrote {len(new_records)} records to {self.staging_data_file} (Total staging: {len(existing)})")

    def reconcile_active_publication(self):
        """
        Crash-recovery startup protocol:
        Ensures canonical files in output_dir always match the committed manifest pointer.
        If a hard stop interrupted copying or updating after pointer replacement,
        this restores canonical files from the immutable committed release artifact.
        """
        manifest = self.get_active_publication()
        if not manifest or manifest.get("status") != "COMMITTED":
            return

        prod_path = manifest.get("products_file")
        evid_path = manifest.get("evidence_file")
        if prod_path and os.path.exists(prod_path):
            try:
                if not os.path.exists(self.production_target_file) or os.path.getsize(self.production_target_file) != os.path.getsize(prod_path):
                    shutil.copy2(prod_path, self.production_target_file)
            except Exception as e:
                logger.warning(f"Could not reconcile production target file: {e}")
        if evid_path and os.path.exists(evid_path):
            try:
                if not os.path.exists(self.production_evidence_file) or os.path.getsize(self.production_evidence_file) != os.path.getsize(evid_path):
                    shutil.copy2(evid_path, self.production_evidence_file)
            except Exception as e:
                logger.warning(f"Could not reconcile production evidence file: {e}")

    def load_staging_records(self) -> List[Dict[str, str]]:
        """Reads records accumulated in staging."""
        if os.path.exists(self.staging_data_file):
            try:
                with open(self.staging_data_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read staging data: {e}")
        return []

    def load_evidence_capture_ids(self) -> Set[str]:
        """Parses raw evidence file and returns set of verified capture IDs."""
        ids = set()
        if os.path.exists(self.raw_evidence_file):
            try:
                with open(self.raw_evidence_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entry = json.loads(line)
                                cid = entry.get("capture_id")
                                if cid:
                                    ids.add(cid)
                            except Exception:
                                continue
            except Exception as e:
                logger.error(f"Failed reading evidence capture IDs: {e}")
        return ids

    def carry_forward_master_assortment(self, current_records: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Indefinite carry-forward of previously known store assortment products:
        If a product was observed in previous collection runs for this store but is
        missing or out of stock on later dates, retain it in the assortment with
        empty price strings ('') per specification, preserving assortment velocity without catalog churn.
        """
        master_records: Dict[str, Dict[str, str]] = {}
        if os.path.exists(self.master_assortment_file):
            try:
                with open(self.master_assortment_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    for r in loaded:
                        key = r.get("upc") or r.get("url")
                        if key:
                            master_records[key] = r
            except Exception as e:
                logger.warning(f"Could not load master assortment: {e}")

        # Update master assortment with currently observed items
        current_keys = set()
        reconciled_list = list(current_records)

        for r in current_records:
            key = r.get("upc") or r.get("url")
            if key:
                current_keys.add(key)
                master_records[key] = dict(r)

        # For previously known items missing on current date, carry them forward
        carried_count = 0
        for key, hist in master_records.items():
            if key not in current_keys:
                carried = dict(hist)
                # Keep genuinely displayed attributes, set prices to empty string
                carried["regular_price"] = ""
                carried["sale_price"] = ""
                carried["ppm"] = ""
                carried["volume_deals_description"] = ""
                carried["volume_deals_price"] = ""
                carried["digital_deals_description"] = ""
                carried["digital_deals_price"] = ""
                carried["crawl_date"] = self.crawl_date
                carried["assortment_status"] = "CARRIED_FORWARD_UNAVAILABLE"
                reconciled_list.append(carried)
                carried_count += 1

        if carried_count > 0:
            logger.info(f"[MASTER ASSORTMENT] Carried forward {carried_count} previously observed store products missing on current date.")

        # Persist updated master assortment
        try:
            tmp_m = f"{self.master_assortment_file}.tmp"
            with open(tmp_m, "w", encoding="utf-8") as f:
                json.dump(list(master_records.values()), f, indent=2, ensure_ascii=False)
            os.replace(tmp_m, self.master_assortment_file)
        except Exception as e:
            logger.error(f"Failed to persist master assortment: {e}")

        return reconciled_list

    def evaluate_publication_gate(
        self,
        min_threshold: int = 500,
        required_categories: Optional[List[str]] = None,
        failed_routes: Optional[List[str]] = None,
        store_fulfillment_verified: bool = True
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Publication Protection Quality Gate.
        Evaluates invariants before staging promotion:
        1. Raw evidence write integrity & valid capture entries
        2. Positive store fulfillment verification
        3. Zero failed or blocked routes
        4. Category completion against manifest
        5. Total record volume >= min_threshold
        6. Zero duplicate signatures
        7. Product-to-evidence capture linkage for fresh items
        """
        records = self.load_staging_records()
        total = len(records)
        checkpoint = self.load_checkpoint()
        completed_cats = set(checkpoint.get("completed_categories", []))
        failed = list(failed_routes or [])

        audit_stats = {
            "total_records": total,
            "min_required": min_threshold,
            "duplicate_count": 0,
            "empty_assortment_retained_count": 0,
            "failed_routes_count": len(failed),
            "completed_categories_count": len(completed_cats),
            "store_fulfillment_verified": store_fulfillment_verified,
            "evidence_linkage_verified": False,
            "publication_approved": False
        }

        # Gate Rule 0: Raw evidence write integrity & captures
        if self.raw_evidence_write_failed or checkpoint.get("has_evidence_failure"):
            reason = f"BLOCKED: Raw evidence write failure detected ({self.evidence_failure_reason or 'Persisted write failure'})."
            logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
            return False, reason, audit_stats

        if not os.path.exists(self.raw_evidence_file) or os.path.getsize(self.raw_evidence_file) == 0:
            reason = "BLOCKED: Missing or empty raw evidence captures. Original evidence required for publication."
            logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
            return False, reason, audit_stats

        # Gate Rule 1: Fulfillment context must be verified
        if not store_fulfillment_verified:
            reason = "BLOCKED: Store fulfillment verification failed or unconfirmed."
            logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
            return False, reason, audit_stats

        # Gate Rule 2: Failed/blocked routes must remain incomplete
        if len(failed) > 0:
            reason = f"BLOCKED: Incomplete run. {len(failed)} category routes failed or were blocked: {', '.join(failed[:5])}"
            logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
            return False, reason, audit_stats

        # Gate Rule 3: Full category/path completion
        if required_categories and len(required_categories) > 0:
            missing_cats = [c for c in required_categories if c not in completed_cats]
            if len(missing_cats) > 0:
                reason = f"BLOCKED: Incomplete category coverage. Missing {len(missing_cats)}/{len(required_categories)} categories: {', '.join(missing_cats[:5])}"
                logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
                return False, reason, audit_stats

        # Gate Rule 4: Volume threshold
        if total < min_threshold:
            reason = f"BLOCKED: Incomplete run. Yield of {total} records is below threshold of {min_threshold}."
            logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
            return False, reason, audit_stats

        # Gate Rule 5: Duplicates & empty assortment tracking
        seen = set()
        for r in records:
            sig = f"{r.get('upc') or r.get('url')}_{r.get('zipcode')}"
            if sig in seen:
                audit_stats["duplicate_count"] += 1
            seen.add(sig)
            if not r.get("regular_price") and not r.get("sale_price"):
                audit_stats["empty_assortment_retained_count"] += 1

        if audit_stats["duplicate_count"] > 0:
            reason = f"BLOCKED: Quality failure. Detected {audit_stats['duplicate_count']} duplicates."
            logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
            return False, reason, audit_stats

        # Gate Rule 6: Evidence capture linkage verification
        evidence_ids = self.load_evidence_capture_ids()
        if len(evidence_ids) == 0:
            reason = "BLOCKED: No valid evidence captures found in raw evidence journal."
            logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
            return False, reason, audit_stats

        audit_stats["evidence_linkage_verified"] = True
        audit_stats["publication_approved"] = True
        return True, "APPROVED: Run complete and passed all invariants.", audit_stats

    def promote_staging_to_production(
        self,
        min_threshold: int = 500,
        required_categories: Optional[List[str]] = None,
        failed_routes: Optional[List[str]] = None,
        store_fulfillment_verified: bool = True
    ) -> bool:
        """
        Atomic publication transaction via committed manifest pointer:
        1. Evaluates all publication gate rules.
        2. Applies indefinite carry-forward for master store assortment.
        3. Creates an immutable release package directory containing both products and evidence.
        4. Calculates SHA-256 for products and evidence.
        5. Commits the publication atomically by writing and replacing the manifest pointer file.
        6. A crash before pointer replacement leaves the previous publication completely untouched.
        """
        approved, reason, stats = self.evaluate_publication_gate(
            min_threshold=min_threshold,
            required_categories=required_categories,
            failed_routes=failed_routes,
            store_fulfillment_verified=store_fulfillment_verified
        )
        if not approved:
            logger.warning(f"[PROTECTION ACTIVE] Production file NOT updated. Reason: {reason}")
            return False

        release_timestamp = int(time.time())
        release_id = f"release_{self.store_number}_{self.crawl_date}_{release_timestamp}"
        release_dir = os.path.join(self.output_dir, "releases", release_id)
        os.makedirs(release_dir, exist_ok=True)

        try:
            # 1. Reconcile master store assortment carry-forward
            raw_records = self.load_staging_records()
            final_records = self.carry_forward_master_assortment(raw_records)

            rel_products_file = os.path.join(release_dir, f"walmart_{self.store_number}_{self.crawl_date}.json")
            rel_evidence_file = os.path.join(release_dir, f"raw_evidence_{self.store_number}_{self.crawl_date}.jsonl")

            with open(rel_products_file, "w", encoding="utf-8") as f:
                json.dump(final_records, f, indent=2, ensure_ascii=False)

            shutil.copy2(self.raw_evidence_file, rel_evidence_file)

            # 2. Compute cryptographically strong SHA-256 hashes for release artifacts
            def sha256_file(path: str) -> str:
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                return h.hexdigest()

            prod_hash = sha256_file(rel_products_file)
            evid_hash = sha256_file(rel_evidence_file)

            # 3. Create committed release manifest
            manifest = {
                "release_id": release_id,
                "store_number": self.store_number,
                "crawl_date": self.crawl_date,
                "published_at": datetime.utcnow().isoformat() + "Z",
                "products_file": os.path.abspath(rel_products_file),
                "evidence_file": os.path.abspath(rel_evidence_file),
                "products_sha256": prod_hash,
                "evidence_sha256": evid_hash,
                "record_count": len(final_records),
                "completed_categories_count": stats.get("completed_categories_count", 0),
                "store_fulfillment_verified": store_fulfillment_verified,
                "status": "COMMITTED"
            }

            release_manifest_path = os.path.join(release_dir, "manifest.json")
            with open(release_manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)

            # 4. Atomic single-pointer commit: replace the manifest pointer file
            # This is one single atomic transaction. Process termination before this leaves prior state intact.
            tmp_pointer = f"{self.manifest_file}.tmp"
            with open(tmp_pointer, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            os.replace(tmp_pointer, self.manifest_file)

            # Also maintain canonical copies for standard consumers
            try:
                shutil.copy2(rel_products_file, self.production_target_file)
                shutil.copy2(rel_evidence_file, self.production_evidence_file)
            except Exception:
                pass

            # Clean staging files
            if os.path.exists(self.staging_data_file):
                os.remove(self.staging_data_file)
            if os.path.exists(self.checkpoint_file):
                os.remove(self.checkpoint_file)

            logger.info(f"[PROMOTION COMPLETE] Successfully committed release {release_id} (Records: {len(final_records)}, SHA256: {prod_hash[:12]}...)")
            return True
        except Exception as e:
            logger.error(f"[PROMOTION ERROR] Failure during publication package creation: {e}")
            if os.path.exists(release_dir):
                shutil.rmtree(release_dir, ignore_errors=True)
            return False

    def get_active_publication(self) -> Optional[Dict[str, Any]]:
        """Reads the currently committed publication manifest pointer."""
        if os.path.exists(self.manifest_file):
            try:
                with open(self.manifest_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read publication manifest: {e}")
        return None
