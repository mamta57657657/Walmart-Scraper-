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
import uuid
import re
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime

try:
    from validation import sanitize_and_order_record, validate_dataset, REQUIRED_FIELD_ORDER
except ImportError:
    from scraper.validation import sanitize_and_order_record, validate_dataset, REQUIRED_FIELD_ORDER

logger = logging.getLogger("CheckpointManager")


def compute_routes_signature(routes: List[Dict[str, str]]) -> str:
    """Computes a canonical SHA-256 signature binding a checkpoint to its exact category/sub-category/URL route list."""
    canonical = [
        f"{str(r.get('category', '')).strip()}>{str(r.get('sub_category', '')).strip()}::{str(r.get('walmart_url', '')).strip()}"
        for r in routes
    ]
    return hashlib.sha256("\n".join(canonical).encode("utf-8")).hexdigest()


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
    1. Store & Route-Bound Checkpoint Journaling: Binds state to store_number & routes_signature.
    2. Restart Staging Reconciliation: Invalidates routes whose staged rows are missing on disk.
    3. Cross-Midnight Resumption: Preserves crawl session and staging files across midnight.
    4. Historical Observation Date Preservation: Keeps each row's original crawl_date intact.
    5. Per-Row Raw Evidence Linkage: Verifies every exported row backs onto saved store evidence.
    6. Unique Collision-Free Release Directories & Pre-Switch Verification before atomic pointer swap.
    7. Strict 22-Field Output Enforcement on release publication.
    """

    ACTIVE_RESUMABLE_STATUSES = {"IN_PROGRESS", "INTERRUPTED", "PARTIAL_WITH_FAILURES", "STOPPED_AT_LIMIT"}

    def __init__(
        self,
        store_number: str,
        crawl_date: str,
        staging_dir: str = ".staging",
        output_dir: str = "output",
        routes_signature: str = "",
        run_id: str = "",
        store_zipcode: str = "",
    ):
        self.store_number = str(store_number)
        self.store_zipcode = str(store_zipcode or "")
        self.crawl_date = crawl_date
        self.staging_dir = staging_dir
        self.output_dir = output_dir
        self.routes_signature = str(routes_signature or "")
        self.run_id = str(run_id or f"run_{self.store_number}_{self.crawl_date}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}")

        os.makedirs(self.staging_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        # Check for cross-midnight active checkpoint before setting file paths
        active_date = self._find_active_in_progress_date()
        if active_date and active_date != self.crawl_date:
            logger.info(f"[CROSS-MIDNIGHT RESUME] Detected active resumable crawl from {active_date}. Preserving session date.")
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

    def _atomic_write_json(self, path: str, payload: Any):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        temp_path = f"{path}.tmp.{uuid.uuid4().hex[:6]}"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)

    def _atomic_copy_file(self, src_path: str, dst_path: str):
        os.makedirs(os.path.dirname(os.path.abspath(dst_path)), exist_ok=True)
        temp_dst = f"{dst_path}.tmp.{uuid.uuid4().hex[:6]}"
        shutil.copy2(src_path, temp_dst)
        os.replace(temp_dst, dst_path)

    def _find_active_in_progress_date(self) -> Optional[str]:
        """Detects if a resumable crawl for this store & routes started on an earlier date."""
        pattern = os.path.join(self.staging_dir, f"checkpoint_{self.store_number}_*.json")
        for cp_path in sorted(glob.glob(pattern)):
            try:
                with open(cp_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("status") not in self.ACTIVE_RESUMABLE_STATUSES:
                        continue
                    if str(data.get("store_number")) != self.store_number:
                        continue
                    cp_sig = str(data.get("routes_signature") or "")
                    if self.routes_signature and cp_sig and cp_sig != self.routes_signature:
                        continue
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
        try:
            self._atomic_write_json(self.checkpoint_file, cp)
        except Exception as e:
            logger.error(f"Failed to persist evidence failure status: {e}")

    def append_raw_evidence(
        self,
        endpoint: str,
        request_data: Any,
        response_payload: Any,
        run_id: Optional[str] = None
    ) -> str:
        """
        Durable persistence of original intercepted network responses.
        Returns a unique capture_id for product-to-evidence linkage.
        Sanitizes sensitive headers and tokens.
        Raises IOError and sets persisted failure flag on write errors.
        """
        self.raw_evidence_count += 1
        capture_id = f"cap_{self.store_number}_{int(time.time()*1000)}_{self.raw_evidence_count}_{uuid.uuid4().hex[:4]}"

        sanitized_req = sanitize_captured_request(request_data)

        entry = {
            "capture_id": capture_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "store_number": self.store_number,
            "crawl_date": self.crawl_date,
            "run_id": run_id or self.run_id,
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

    def _fresh_checkpoint_state(self, status: str = "INITIALIZED", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state = {
            "store_number": self.store_number,
            "store_zipcode": self.store_zipcode,
            "crawl_date": self.crawl_date,
            "run_id": self.run_id,
            "routes_signature": self.routes_signature,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "category_index": 0,
            "current_page": 1,
            "completed_categories": [],
            "category_yields": {},
            "terminal_verified_routes": {},
            "failed_routes": [],
            "flushed_records_count": 0,
            "seen_record_signatures": [],
            "confirmed_store_number": "",
            "requests_made": 0,
            "status": status,
        }
        if extra:
            state.update(extra)
        return state

    def load_checkpoint(self, expected_routes_signature: Optional[str] = None) -> Dict[str, Any]:
        """
        Loads existing checkpoint if run was interrupted.
        Enforces store_number and routes_signature binding and diagnoses corruption safely.
        """
        target_sig = expected_routes_signature if expected_routes_signature is not None else self.routes_signature
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                cp_store = str(data.get("store_number") or "")
                cp_sig = str(data.get("routes_signature") or "")
                if cp_store and cp_store != self.store_number:
                    mismatch_backup = f"{self.checkpoint_file}.mismatch.{int(time.time())}"
                    shutil.copy2(self.checkpoint_file, mismatch_backup)
                    reason = f"Checkpoint store '{cp_store}' does not match configured store '{self.store_number}'"
                    logger.warning(f"[CHECKPOINT MISMATCH] {reason}. Isolating incompatible checkpoint.")
                    return self._fresh_checkpoint_state(
                        status="CHECKPOINT_MISMATCH_RESET",
                        extra={"mismatch_reason": reason, "mismatch_backup_file": mismatch_backup},
                    )
                if target_sig and cp_sig and cp_sig != target_sig:
                    mismatch_backup = f"{self.checkpoint_file}.mismatch.{int(time.time())}"
                    shutil.copy2(self.checkpoint_file, mismatch_backup)
                    reason = f"Checkpoint routes signature '{cp_sig[:12]}' does not match configured routes '{target_sig[:12]}'"
                    logger.warning(f"[CHECKPOINT MISMATCH] {reason}. Isolating incompatible checkpoint.")
                    return self._fresh_checkpoint_state(
                        status="CHECKPOINT_MISMATCH_RESET",
                        extra={"mismatch_reason": reason, "mismatch_backup_file": mismatch_backup},
                    )

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

                return self._fresh_checkpoint_state(
                    status="RECOVERED_FROM_CORRUPTION",
                    extra={"corruption_diagnostic": str(e), "corrupt_backup_file": corrupt_backup},
                )

        return self._fresh_checkpoint_state(status="INITIALIZED")

    def reconcile_staged_routes_on_resume(
        self,
        cp_state: Dict[str, Any],
        staged_records: List[Dict[str, str]],
        ordered_routes: Optional[List[Dict[str, str]]] = None,
    ) -> Tuple[Dict[str, int], List[str], Dict[str, Any], int, List[str]]:
        """
        Reconciles checkpoint completion metadata against actual staging rows present on disk.
        If staged rows for a completed route are missing or short relative to recorded yield,
        that route is removed from completed/yields/terminal_verified and re-queued in failed_routes.
        """
        category_yields: Dict[str, int] = dict(cp_state.get("category_yields") or {})
        failed_routes: List[str] = list(cp_state.get("failed_routes") or [])
        terminal_verified: Dict[str, Any] = dict(cp_state.get("terminal_verified_routes") or {})
        completed_list = list(cp_state.get("completed_categories") or [])
        expected_flushed = int(cp_state.get("flushed_records_count") or 0)
        warnings: List[str] = []

        actual_counts: Dict[str, int] = {}
        for r in staged_records:
            rk = f"{r.get('category', '')} > {r.get('sub_category', '')}"
            actual_counts[rk] = actual_counts.get(rk, 0) + 1

        invalidated_routes: Set[str] = set()
        for rk in list(set(list(category_yields.keys()) + completed_list)):
            expected_y = int(category_yields.get(rk, 0))
            actual_y = actual_counts.get(rk, 0)
            if (expected_y > 0 and actual_y < expected_y) or (expected_flushed > len(staged_records) and actual_y == 0):
                invalidated_routes.add(rk)
                msg = (
                    f"[STAGING RECONCILIATION] Route '{rk}' expected {expected_y} staged row(s) "
                    f"but disk staging has {actual_y} (total staged={len(staged_records)} vs flushed={expected_flushed}). Re-queueing route."
                )
                logger.warning(msg)
                warnings.append(msg)

        for rk in invalidated_routes:
            category_yields.pop(rk, None)
            terminal_verified.pop(rk, None)
            if rk not in failed_routes:
                failed_routes.append(rk)

        # Also check current active incomplete route if its rows disappeared
        resumed_page = max(1, int(cp_state.get("current_page") or 1))
        if ordered_routes and expected_flushed > len(staged_records):
            cp_idx = int(cp_state.get("category_index") or 0)
            if 0 <= cp_idx < len(ordered_routes):
                active_rk = f"{ordered_routes[cp_idx].get('category', '')} > {ordered_routes[cp_idx].get('sub_category', '')}"
                if actual_counts.get(active_rk, 0) == 0 and resumed_page > 1:
                    resumed_page = 1
                    if active_rk not in failed_routes:
                        failed_routes.append(active_rk)

        if invalidated_routes and ordered_routes:
            for idx, item in enumerate(ordered_routes):
                rk = f"{item.get('category', '')} > {item.get('sub_category', '')}"
                if rk in invalidated_routes:
                    resumed_page = 1
                    break

        return category_yields, failed_routes, terminal_verified, resumed_page, warnings

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
        failed_routes: Optional[List[str]] = None,
        routes_signature: Optional[str] = None,
        run_id: Optional[str] = None,
        terminal_verified_routes: Optional[Dict[str, Any]] = None,
        confirmed_store_number: Optional[str] = None,
        requests_made: Optional[int] = None,
        stop_reason: str = "",
    ):
        """Atomically saves store- and route-bound checkpoint to disk."""
        state = {
            "store_number": self.store_number,
            "store_zipcode": self.store_zipcode,
            "crawl_date": self.crawl_date,
            "run_id": run_id or self.run_id,
            "routes_signature": routes_signature if routes_signature is not None else self.routes_signature,
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "category_index": category_index,
            "current_page": current_page,
            "completed_categories": list(completed_categories),
            "category_yields": category_yields or {},
            "terminal_verified_routes": terminal_verified_routes or {},
            "failed_routes": list(failed_routes or []),
            "flushed_records_count": flushed_count,
            "seen_record_signatures": list(seen_signatures),
            "confirmed_store_number": confirmed_store_number or "",
            "requests_made": requests_made if requests_made is not None else 0,
            "stop_reason": stop_reason,
            "has_evidence_failure": self.raw_evidence_write_failed,
            "evidence_failure_reason": self.evidence_failure_reason,
            "status": status
        }
        try:
            self._atomic_write_json(self.checkpoint_file, state)
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
        status: str = "IN_PROGRESS",
        routes_signature: Optional[str] = None,
        run_id: Optional[str] = None,
        terminal_verified_routes: Optional[Dict[str, Any]] = None,
        confirmed_store_number: Optional[str] = None,
        requests_made: Optional[int] = None,
        stop_reason: str = "",
    ):
        """
        Durable single page transaction:
        1. Atomically appends batch records to staging file.
        2. Directly reconciles deduplication signatures from the updated staging file.
        3. Atomically writes the store- and route-bound checkpoint referencing exact staging count.
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
            failed_routes=failed_routes,
            routes_signature=routes_signature,
            run_id=run_id,
            terminal_verified_routes=terminal_verified_routes,
            confirmed_store_number=confirmed_store_number,
            requests_made=requests_made,
            stop_reason=stop_reason,
        )

    def append_staging_records(self, new_records: List[Dict[str, str]]):
        """Flushes verified batch records into staging storage immediately."""
        existing = self.load_staging_records()
        existing.extend(new_records)
        self._atomic_write_json(self.staging_data_file, existing)
        logger.info(f"[STAGING FLUSH] Wrote {len(new_records)} records to {self.staging_data_file} (Total staging: {len(existing)})")

    def reconcile_active_publication(self):
        """
        Crash-recovery startup protocol:
        Ensures canonical files in output_dir always match the committed manifest pointer
        for the committed crawl_date without mislabeling prior deliveries onto a new crawl_date.
        """
        manifest = self.get_active_publication()
        if not manifest or manifest.get("status") != "COMMITTED":
            return

        committed_date = manifest.get("crawl_date") or self.crawl_date
        committed_target = os.path.join(self.output_dir, f"walmart_{self.store_number}_{committed_date}.json")
        committed_evidence = os.path.join(self.output_dir, f"raw_evidence_{self.store_number}_{committed_date}.jsonl")

        prod_path = manifest.get("products_file")
        evid_path = manifest.get("evidence_file")
        if prod_path and os.path.exists(prod_path):
            try:
                if not os.path.exists(committed_target) or os.path.getsize(committed_target) != os.path.getsize(prod_path):
                    self._atomic_copy_file(prod_path, committed_target)
            except Exception as e:
                logger.warning(f"Could not reconcile production target file: {e}")
        if evid_path and os.path.exists(evid_path):
            try:
                if not os.path.exists(committed_evidence) or os.path.getsize(committed_evidence) != os.path.getsize(evid_path):
                    self._atomic_copy_file(evid_path, committed_evidence)
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

    def load_evidence_capture_map(self) -> Dict[str, Dict[str, Any]]:
        """Parses raw evidence JSONL file and returns a map of capture_id -> evidence entry."""
        captures: Dict[str, Dict[str, Any]] = {}
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
                                    captures[str(cid)] = entry
                            except Exception:
                                continue
            except Exception as e:
                logger.error(f"Failed reading evidence capture map: {e}")
        return captures

    def load_evidence_capture_ids(self) -> Set[str]:
        """Parses raw evidence file and returns set of verified capture IDs."""
        return set(self.load_evidence_capture_map().keys())

    def carry_forward_master_assortment(self, current_records: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Indefinite carry-forward of previously known store assortment products:
        Preserves each carried-forward row's original historical observation crawl_date
        while resetting unavailable price fields to '' per specification.
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
        reconciled_list = [dict(r) for r in current_records]

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
                # Keep genuinely displayed attributes and original historical crawl_date!
                carried["regular_price"] = ""
                carried["sale_price"] = ""
                carried["ppm"] = ""
                carried["volume_deals_description"] = ""
                carried["volume_deals_price"] = ""
                carried["digital_deals_description"] = ""
                carried["digital_deals_price"] = ""
                carried["crawl_date"] = str(hist.get("crawl_date") or "").strip() or self.crawl_date
                carried["assortment_status"] = "CARRIED_FORWARD_UNAVAILABLE"
                reconciled_list.append(carried)
                carried_count += 1

        if carried_count > 0:
            logger.info(f"[MASTER ASSORTMENT] Carried forward {carried_count} previously observed store products preserving original observation dates.")

        # Persist updated master assortment atomically
        try:
            self._atomic_write_json(self.master_assortment_file, list(master_records.values()))
        except Exception as e:
            logger.error(f"Failed to persist master assortment: {e}")

        return reconciled_list

    def evaluate_publication_gate(
        self,
        min_threshold: int = 500,
        required_categories: Optional[List[str]] = None,
        failed_routes: Optional[List[str]] = None,
        store_fulfillment_verified: bool = True,
        terminal_verified_routes: Optional[Dict[str, Any]] = None,
        confirmed_store_number: Optional[str] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Publication Protection Quality Gate.
        Evaluates invariants before staging promotion:
        1. Raw evidence write integrity & valid capture entries
        2. Positive store fulfillment verification matching configured store
        3. Zero failed or blocked routes
        4. Category & child route completion + terminal verification against CSV manifest
        5. Total record volume >= min_threshold
        6. Zero duplicate signatures
        7. Per-row product-to-evidence capture linkage matching configured store
        """
        records = self.load_staging_records()
        total = len(records)
        checkpoint = self.load_checkpoint()
        completed_cats = set(checkpoint.get("completed_categories", []))
        cp_terminal = checkpoint.get("terminal_verified_routes") or {}
        eff_terminal = terminal_verified_routes if terminal_verified_routes is not None else cp_terminal
        failed = list(failed_routes or [])

        audit_stats = {
            "total_records": total,
            "min_required": min_threshold,
            "duplicate_count": 0,
            "empty_assortment_retained_count": 0,
            "failed_routes_count": len(failed),
            "completed_categories_count": len(completed_cats),
            "store_fulfillment_verified": store_fulfillment_verified,
            "confirmed_store_number": confirmed_store_number or checkpoint.get("confirmed_store_number", ""),
            "unverified_rows_count": 0,
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

        # Gate Rule 1: Fulfillment context must be verified & store match
        if not store_fulfillment_verified:
            reason = "BLOCKED: Store fulfillment verification failed or unconfirmed."
            logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
            return False, reason, audit_stats

        eff_confirmed_store = str(confirmed_store_number or checkpoint.get("confirmed_store_number") or "").strip()
        if eff_confirmed_store and eff_confirmed_store != str(self.store_number):
            reason = f"BLOCKED: Confirmed store '{eff_confirmed_store}' mismatches target store '{self.store_number}'."
            logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
            return False, reason, audit_stats

        # Gate Rule 2: Failed/blocked routes must remain incomplete
        if len(failed) > 0:
            reason = f"BLOCKED: Incomplete run. {len(failed)} category routes failed or were blocked: {', '.join(failed[:5])}"
            logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
            return False, reason, audit_stats

        # Gate Rule 3: Full category/child route & terminal page completion
        if required_categories and len(required_categories) > 0:
            missing_cats = [c for c in required_categories if c not in completed_cats]
            if len(missing_cats) > 0:
                reason = f"BLOCKED: Incomplete category coverage. Missing {len(missing_cats)}/{len(required_categories)} categories: {', '.join(missing_cats[:5])}"
                logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
                return False, reason, audit_stats

            unverified_terminal = []
            for c in required_categories:
                tv = eff_terminal.get(c)
                if not isinstance(tv, dict) or not tv.get("terminal_verified"):
                    unverified_terminal.append(c)
                elif tv.get("store_number") and str(tv.get("store_number")) != str(self.store_number):
                    unverified_terminal.append(c)
            if unverified_terminal:
                reason = (
                    f"BLOCKED: Terminal page verification missing for {len(unverified_terminal)}/{len(required_categories)} "
                    f"required route(s): {', '.join(unverified_terminal[:5])}"
                )
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

        # Gate Rule 6: Per-row evidence capture linkage verification
        evidence_map = self.load_evidence_capture_map()
        if len(evidence_map) == 0:
            reason = "BLOCKED: No valid evidence captures found in raw evidence journal."
            logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
            return False, reason, audit_stats

        unverified_rows = 0
        for r in records:
            cid = str(r.get("capture_id") or "").strip()
            ev_entry = evidence_map.get(cid) if cid else None
            if ev_entry is None:
                unverified_rows += 1
            elif ev_entry.get("store_number") and str(ev_entry.get("store_number")) != str(self.store_number):
                unverified_rows += 1

        audit_stats["unverified_rows_count"] = unverified_rows
        if unverified_rows > 0:
            reason = (
                f"BLOCKED: Evidence linkage failure. {unverified_rows}/{total} exported row(s) "
                f"lack matching saved raw evidence for Store #{self.store_number}."
            )
            logger.error(f"[PUBLICATION GATE BLOCKED] {reason}")
            return False, reason, audit_stats

        audit_stats["evidence_linkage_verified"] = True
        audit_stats["publication_approved"] = True
        return True, "APPROVED: Run complete and passed all invariants.", audit_stats

    def verify_release_package(
        self,
        release_dir: str,
        manifest: Dict[str, Any],
        expected_store_number: str,
        min_expected: int = 1,
    ) -> Tuple[bool, str]:
        """
        Pre-switch verification: validates release files, SHA-256 checksums,
        exact 22-field schema, and store metadata on disk BEFORE switching manifest pointer.
        """
        try:
            rel_products = manifest.get("products_file", "")
            rel_evidence = manifest.get("evidence_file", "")
            rel_manifest = os.path.join(release_dir, "manifest.json")

            for p in (rel_products, rel_evidence, rel_manifest):
                if not p or not os.path.exists(p) or os.path.getsize(p) == 0:
                    return False, f"Missing or empty release artifact: {p}"

            with open(rel_products, "r", encoding="utf-8") as f:
                loaded_products = json.load(f)
            if not isinstance(loaded_products, list):
                return False, "Release products file does not contain a JSON array"
            if len(loaded_products) != int(manifest.get("record_count", -1)):
                return False, f"Product count mismatch: disk={len(loaded_products)} vs manifest={manifest.get('record_count')}"

            expected_zips = {self.store_zipcode} if self.store_zipcode else None
            is_valid, stats = validate_dataset(
                loaded_products,
                min_expected=min_expected,
                expected_zipcodes=expected_zips,
            )
            if not is_valid:
                return False, f"Export schema validation failed before switch: {stats.get('errors')}"

            def sha256_file(path: str) -> str:
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                return h.hexdigest()

            if sha256_file(rel_products) != manifest.get("products_sha256"):
                return False, "Products SHA-256 verification failed before pointer switch"
            if sha256_file(rel_evidence) != manifest.get("evidence_sha256"):
                return False, "Evidence SHA-256 verification failed before pointer switch"

            # Verify raw evidence JSONL lines parse cleanly and match store_number
            evidence_lines = 0
            with open(rel_evidence, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    obj = json.loads(s)
                    if obj.get("store_number") and str(obj.get("store_number")) != str(expected_store_number):
                        return False, f"Evidence entry store mismatch: {obj.get('store_number')} != {expected_store_number}"
                    evidence_lines += 1
            if evidence_lines == 0:
                return False, "Release evidence JSONL contains 0 valid JSON entries"

            with open(rel_manifest, "r", encoding="utf-8") as f:
                disk_manifest = json.load(f)
            if disk_manifest.get("release_id") != manifest.get("release_id") or disk_manifest.get("status") != "COMMITTED":
                return False, "Release manifest verification failed before pointer switch"

            return True, "Release package verified cleanly"
        except Exception as ex:
            return False, f"Pre-switch release verification error: {ex}"

    def promote_staging_to_production(
        self,
        min_threshold: int = 500,
        required_categories: Optional[List[str]] = None,
        failed_routes: Optional[List[str]] = None,
        store_fulfillment_verified: bool = True,
        terminal_verified_routes: Optional[Dict[str, Any]] = None,
        confirmed_store_number: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> bool:
        """
        Atomic publication transaction via committed manifest pointer:
        1. Evaluates all publication gate rules (including per-row evidence).
        2. Applies indefinite carry-forward preserving historical observation dates.
        3. Projects every exported record strictly onto REQUIRED_FIELD_ORDER (22 fields).
        4. Writes to a collision-free unique release directory (`os.makedirs(..., exist_ok=False)`).
        5. Verifies all release files, schema, and SHA-256 checksums BEFORE switching pointer.
        6. Atomically replaces the manifest pointer (`os.replace`). Failures never delete prior releases.
        """
        approved, reason, stats = self.evaluate_publication_gate(
            min_threshold=min_threshold,
            required_categories=required_categories,
            failed_routes=failed_routes,
            store_fulfillment_verified=store_fulfillment_verified,
            terminal_verified_routes=terminal_verified_routes,
            confirmed_store_number=confirmed_store_number,
        )
        if not approved:
            logger.warning(f"[PROTECTION ACTIVE] Production file NOT updated. Reason: {reason}")
            return False

        release_id = f"release_{self.store_number}_{self.crawl_date}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        release_dir = os.path.join(self.output_dir, "releases", release_id)
        dir_created_by_this_call = False

        try:
            os.makedirs(release_dir, exist_ok=False)
            dir_created_by_this_call = True

            # 1. Reconcile master store assortment carry-forward (preserving historical observation dates)
            raw_records = self.load_staging_records()
            carried_records = self.carry_forward_master_assortment(raw_records)

            # Enforce strict 22-field output schema on every exported record (strip internal meta keys)
            final_records = [
                sanitize_and_order_record(
                    r,
                    crawl_date=str(r.get("crawl_date") or "").strip() or self.crawl_date,
                    preserve_meta=False,
                )
                for r in carried_records
            ]

            expected_zips = {self.store_zipcode} if self.store_zipcode else None
            schema_ok, schema_stats = validate_dataset(
                final_records,
                min_expected=min_threshold,
                expected_zipcodes=expected_zips,
            )
            if not schema_ok:
                raise ValueError(f"Output schema validation rejected export: {schema_stats.get('errors')}")

            rel_products_file = os.path.join(release_dir, f"walmart_{self.store_number}_{self.crawl_date}.json")
            rel_evidence_file = os.path.join(release_dir, f"raw_evidence_{self.store_number}_{self.crawl_date}.jsonl")

            self._atomic_write_json(rel_products_file, final_records)
            self._atomic_copy_file(self.raw_evidence_file, rel_evidence_file)

            # 2. Compute cryptographically strong SHA-256 hashes for release artifacts
            def sha256_file(path: str) -> str:
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                return h.hexdigest()

            prod_hash = sha256_file(rel_products_file)
            evid_hash = sha256_file(rel_evidence_file)

            eff_run_id = run_id or self.run_id
            # 3. Create committed release manifest
            manifest = {
                "release_id": release_id,
                "run_id": eff_run_id,
                "store_number": self.store_number,
                "crawl_date": self.crawl_date,
                "published_at": datetime.utcnow().isoformat() + "Z",
                "products_file": os.path.abspath(rel_products_file),
                "evidence_file": os.path.abspath(rel_evidence_file),
                "products_sha256": prod_hash,
                "evidence_sha256": evid_hash,
                "record_count": len(final_records),
                "total_records": len(final_records),
                "completed_categories_count": stats.get("completed_categories_count", 0),
                "store_fulfillment_verified": store_fulfillment_verified,
                "status": "COMMITTED"
            }

            release_manifest_path = os.path.join(release_dir, "manifest.json")
            self._atomic_write_json(release_manifest_path, manifest)

            # 4. Pre-switch package verification before touching reader pointer!
            verified_pkg, verify_msg = self.verify_release_package(
                release_dir=release_dir,
                manifest=manifest,
                expected_store_number=self.store_number,
                min_expected=min_threshold,
            )
            if not verified_pkg:
                raise RuntimeError(f"Pre-switch release verification failed: {verify_msg}")

            # 5. Atomic single-pointer commit: replace the manifest pointer file
            self._atomic_write_json(self.manifest_file, manifest)

            # Also maintain canonical copies atomically for standard consumers
            self._atomic_copy_file(rel_products_file, self.production_target_file)
            self._atomic_copy_file(rel_evidence_file, self.production_evidence_file)

            # Clean staging files only after pointer & canonical copies succeed
            if os.path.exists(self.staging_data_file):
                os.remove(self.staging_data_file)
            if os.path.exists(self.checkpoint_file):
                os.remove(self.checkpoint_file)

            logger.info(
                f"[PROMOTION COMPLETE] Successfully committed release {release_id} "
                f"(Store #{self.store_number}, run_id={eff_run_id}, Records: {len(final_records)}, SHA256: {prod_hash[:12]}...)"
            )
            return True
        except Exception as e:
            logger.error(f"[PROMOTION ERROR] Failure during publication package creation: {e}")
            if dir_created_by_this_call and os.path.exists(release_dir):
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
