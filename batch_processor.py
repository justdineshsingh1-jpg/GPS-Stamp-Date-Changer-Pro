"""
GPS Stamp Date Changer Pro - Batch Processor
Manages concurrent downloads, sequential/even date processing,
real-time status tracking, pause/resume/cancel/retry capabilities,
and safe thread execution.
"""

import os
import re
import time
import shutil
import urllib.request
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Callable, Tuple

from importer import is_safe_url, normalize_google_drive_url, sanitize_url_for_logging
from engine import process_gps_image, extract_time_from_text_or_filename
from date_engine import assign_dates, parse_date_string


def sanitize_filename(filename: str) -> str:
    """Removes invalid characters for Windows filesystem safety."""
    return re.sub(r'[\\/*?:"<>|]', '_', filename).strip()


import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Global thread-safe session with connection pooling
_SESSION = None
_SESSION_LOCK = threading.Lock()
_GDRIVE_SEMAPHORE = threading.Semaphore(3) # Limit concurrent Google Drive requests to prevent IP throttling


def get_download_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        with _SESSION_LOCK:
            if _SESSION is None:
                s = requests.Session()
                retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
                adapter = HTTPAdapter(max_retries=retries, pool_connections=25, pool_maxsize=25)
                s.mount('http://', adapter)
                s.mount('https://', adapter)
                s.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
                })
                _SESSION = s
    return _SESSION


def download_single_image(url: str, out_path: str, max_retries: int = 4, timeout_sec: int = 35) -> Tuple[bool, str]:
    """
    Downloads an image from HTTP/HTTPS or copies from a local path.
    Applies SSRF safety validation, connection pooling, multi-strategy Google Drive downloading,
    and resilient exponential backoff for DNS and socket stability.
    """
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
        return True, "Already cached"

    # Handle local file paths
    url_str = str(url).strip()
    if url_str.startswith("file://") or (len(url_str) > 2 and url_str[1] == ':' and url_str[2] in ('\\', '/')) or url_str.startswith("./") or url_str.startswith("../"):
        local_p = url_str.replace("file://", "")
        if os.path.exists(local_p):
            try:
                shutil.copy2(local_p, out_path)
                return True, "Local copy"
            except Exception as e:
                return False, f"Failed to copy local file: {str(e)}"
        return False, f"Local file not found: {local_p}"

    # Validate SSRF
    is_safe, reason = is_safe_url(url_str)
    if not is_safe:
        return False, f"Blocked by security policy: {reason}"

    session = get_download_session()

    # Detect Google Drive file ID
    gdrive_match = re.search(r'drive\.google\.com/(?:file/d/|open\?id=|uc\?id=)([a-zA-Z0-9_-]+)', url_str)
    if not gdrive_match and "drive.google.com" in url_str:
        gdrive_match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url_str)

    last_error = "Unknown download failure"

    for attempt in range(1, max_retries + 1):
        try:
            if gdrive_match:
                fid = gdrive_match.group(1)
                # Polite concurrency throttle for Google Drive
                with _GDRIVE_SEMAPHORE:
                    urls_to_try = [
                        f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t",
                        f"https://lh3.googleusercontent.com/d/{fid}",
                        f"https://drive.google.com/uc?export=download&id={fid}&confirm=t"
                    ]
                    for u in urls_to_try:
                        try:
                            resp = session.get(u, stream=True, timeout=timeout_sec)
                            if resp.status_code == 200:
                                ct = resp.headers.get('content-type', '').lower()
                                if 'text/html' not in ct:
                                    with open(out_path, 'wb') as f:
                                        for chunk in resp.iter_content(chunk_size=65536):
                                            f.write(chunk)
                                    if os.path.exists(out_path) and os.path.getsize(out_path) > 512:
                                        return True, "Download successful"
                        except Exception as inner_e:
                            last_error = str(inner_e)
            else:
                download_url = normalize_google_drive_url(url_str)
                resp = session.get(download_url, stream=True, timeout=timeout_sec)
                if resp.status_code == 200:
                    ct = resp.headers.get('content-type', '').lower()
                    if 'text/html' not in ct:
                        with open(out_path, 'wb') as f:
                            for chunk in resp.iter_content(chunk_size=65536):
                                f.write(chunk)
                        if os.path.exists(out_path) and os.path.getsize(out_path) > 512:
                            return True, "Download successful"
                last_error = f"HTTP {resp.status_code} ({resp.headers.get('content-type', '')})"
        except Exception as e:
            last_error = str(e)

        # Exponential backoff for DNS and network recovery
        time.sleep(1.5 * attempt)

    return False, f"Download failed after {max_retries} attempts: {last_error}"


class BatchJob:
    """Represents an active or completed bulk processing session."""

    def __init__(self, job_id: str, base_jobs_dir: str):
        self.job_id = job_id
        self.job_dir = os.path.join(base_jobs_dir, job_id)
        self.raw_dir = os.path.join(self.job_dir, "raw_images")
        self.edited_dir = os.path.join(self.job_dir, "edited_images")
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.edited_dir, exist_ok=True)

        self.state = "idle" # idle, downloading, processing, paused, cancelled, completed, error
        self.total = 0
        self.downloaded = 0
        self.processed = 0
        self.succeeded = 0
        self.failed = 0
        self.needs_review = 0
        self.current_index = 0
        self.current_image_id = ""
        self.current_filename = ""
        self.start_time = None
        self.end_time = None
        self.error_message = ""

        self.items: List[Dict[str, Any]] = []
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set() # Unpaused by default
        self.lock = threading.Lock()

        # Export paths
        self.excel_report_path = None
        self.csv_report_path = None
        self.failed_report_path = None
        self.zip_path = None

    def get_progress_data(self) -> Dict[str, Any]:
        """Returns clean progress dictionary for API polling."""
        with self.lock:
            remaining = max(0, self.total - self.processed)
            elapsed_sec = (time.time() - self.start_time) if self.start_time else 0.0
            
            # Estimate remaining seconds
            if self.processed > 0 and self.state in ("downloading", "processing"):
                rate = elapsed_sec / self.processed
                eta_sec = round(rate * remaining)
            else:
                eta_sec = 0

            pct = 0
            if self.total > 0:
                pct = int((self.processed / self.total) * 100)

            return {
                "job_id": self.job_id,
                "state": self.state,
                "total": self.total,
                "downloaded": self.downloaded,
                "processed": self.processed,
                "succeeded": self.succeeded,
                "failed": self.failed,
                "needs_review": self.needs_review,
                "remaining": remaining,
                "percent": pct,
                "current_index": self.current_index,
                "current_image_id": self.current_image_id,
                "current_filename": self.current_filename,
                "elapsed_sec": round(elapsed_sec, 1),
                "eta_sec": eta_sec,
                "error_message": self.error_message,
                "excel_ready": bool(self.excel_report_path and os.path.exists(self.excel_report_path)),
                "csv_ready": bool(self.csv_report_path and os.path.exists(self.csv_report_path)),
                "zip_ready": bool(self.zip_path and os.path.exists(self.zip_path)),
            }

    def pause(self):
        self.pause_event.clear()
        self.state = "paused"

    def resume(self):
        self.pause_event.set()
        self.state = "processing"

    def cancel(self):
        self.stop_event.set()
        self.pause_event.set() # Unblock if paused
        self.state = "cancelled"


def run_batch_pipeline(
    job: BatchJob,
    validated_items: List[Dict[str, Any]],
    date_assignments: List[Dict[str, Any]],
    naming_rule: str = "id_date", # "id_date" or "original"
    preserve_time: bool = True,
    clean_level: str = "standard"
):
    """
    Executes the full background processing pipeline:
      Phase 1: Concurrent downloads with SSRF validation
      Phase 2: High-fidelity GPS overlay stamp date updating
    """
    job.start_time = time.time()
    job.total = len(validated_items)
    job.items = []

    # Initialize item records
    for idx, v_item in enumerate(validated_items):
        d_item = date_assignments[idx] if idx < len(date_assignments) else {}
        
        # Determine target output filename
        img_id = v_item["image_id"]
        date_tag = d_item.get("date_str", "2026-09-24").replace("/", "-")
        
        if naming_rule == "original" and v_item.get("original_url"):
            base = os.path.basename(v_item["original_url"].split("?")[0])
            out_fname = sanitize_filename(base) if base.lower().endswith(('.jpg', '.jpeg', '.png')) else f"{img_id}_{date_tag}.jpg"
        else:
            out_fname = f"{sanitize_filename(img_id)}_{date_tag}.jpg"

        job.items.append({
            "row_id": v_item["row_id"],
            "image_id": img_id,
            "original_url": v_item["original_url"],
            "normalized_url": v_item["normalized_url"],
            "raw_file": f"raw_{v_item['row_id']}.jpg",
            "edited_file": out_fname,
            "assigned_date": d_item.get("date_str", ""),
            "assigned_weekday": d_item.get("weekday", ""),
            "date_dt": d_item.get("date_dt"),
            "status": "pending",
            "error_message": v_item.get("error_message", ""),
            "original_time": "",
            "original_timestamp": "",
            "updated_timestamp": "",
            "confidence": 0.0,
            "detected_layout": "unknown"
        })

    # ==========================================
    # Phase 1: Downloads
    # ==========================================
    job.state = "downloading"
    download_tasks = []

    for item in job.items:
        if job.stop_event.is_set():
            job.state = "cancelled"
            return

        raw_path = os.path.join(job.raw_dir, item["raw_file"])
        if item["error_message"] and "Missing" in item["error_message"]:
            item["status"] = "failed"
            job.failed += 1
            continue

        download_tasks.append((item, raw_path))

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(download_single_image, t[0]["normalized_url"], t[1]): t for t in download_tasks}
        for fut in as_completed(futures):
            item, raw_path = futures[fut]
            if job.stop_event.is_set():
                break
                
            success, msg = fut.result()
            if success:
                job.downloaded += 1
            else:
                item["status"] = "failed"
                item["error_message"] = msg
                with job.lock:
                    job.failed += 1

    if job.stop_event.is_set():
        job.state = "cancelled"
        return

    # ==========================================
    # Phase 2: Stamp Recognition & Date Editing
    # ==========================================
    job.state = "processing"

    for idx, item in enumerate(job.items):
        # Check cancellation
        if job.stop_event.is_set():
            job.state = "cancelled"
            break

        # Check pause
        job.pause_event.wait()

        with job.lock:
            job.current_index = idx + 1
            job.current_image_id = item["image_id"]
            job.current_filename = item["edited_file"]

        # If already failed during download
        if item["status"] == "failed":
            with job.lock:
                job.processed += 1
            continue

        raw_path = os.path.join(job.raw_dir, item["raw_file"])
        out_path = os.path.join(job.edited_dir, item["edited_file"])

        if not os.path.exists(raw_path):
            item["status"] = "failed"
            item["error_message"] = "Downloaded image file missing"
            with job.lock:
                job.failed += 1
                job.processed += 1
            continue

        # Target datetime calculation
        target_dt = item.get("date_dt")
        if not target_dt:
            target_dt = datetime.now()

        # Run high-fidelity stamp processor
        res = process_gps_image(
            input_image_path_or_array=raw_path,
            output_image_path=out_path,
            target_datetime=target_dt,
            clean_level=clean_level
        )

        item["status"] = res["status"]
        item["confidence"] = res.get("confidence", 0.0)
        item["detected_layout"] = res.get("detected_layout", "unknown")

        if res["success"]:
            item["original_time"] = res.get("original_time", "")
            item["updated_timestamp"] = f"{item['assigned_weekday']}, {item['assigned_date']} {item['original_time']}"
            item["error_message"] = ""
            with job.lock:
                job.succeeded += 1
        elif res["status"] == "needs_review":
            item["error_message"] = res.get("message", "Flagged for manual review")
            with job.lock:
                job.needs_review += 1
        else:
            item["error_message"] = res.get("error", "Processing failed")
            with job.lock:
                job.failed += 1

        with job.lock:
            job.processed += 1

    if not job.stop_event.is_set():
        job.state = "completed"
    job.end_time = time.time()
