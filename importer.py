"""
GPS Stamp Date Changer Pro - Importer & URL Validator
Handles CSV and Excel parsing, intelligent column detection,
SSRF security filtering, URL accessibility validation, and duplicate tracking.
"""

import os
import re
import csv
import socket
import ipaddress
import urllib.parse
import urllib.request
from typing import List, Dict, Any, Tuple, Optional
import openpyxl


PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def sanitize_url_for_logging(url: str) -> str:
    """Masks secret query tokens and passwords from URLs for logs and exports."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(str(url))
        if parsed.password:
            netloc = f"{parsed.username or ''}:***@{parsed.hostname}{(':' + str(parsed.port)) if parsed.port else ''}"
        else:
            netloc = parsed.netloc

        # Mask sensitive query params
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        masked_pairs = []
        for k, v in query_pairs:
            k_lower = k.lower()
            if any(s in k_lower for s in ['token', 'secret', 'key', 'auth', 'signature', 'sig']):
                masked_pairs.append((k, "******"))
            else:
                masked_pairs.append((k, v))
                
        masked_query = urllib.parse.urlencode(masked_pairs)
        return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, masked_query, parsed.fragment))
    except Exception:
        return url


def is_safe_url(url: str, allow_local_files: bool = True) -> Tuple[bool, str]:
    """
    Validates URL to protect against SSRF and unsupported protocols.
    Returns (is_safe: bool, reason: str).
    """
    if not url or not str(url).strip():
        return False, "Empty URL"

    url_str = str(url).strip()

    # Local / relative file path support
    is_image_file = any(url_str.lower().endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp'))
    if (is_image_file or 
        url_str.startswith("file://") or 
        (len(url_str) > 2 and url_str[1] == ':' and url_str[2] in ('\\', '/')) or 
        url_str.startswith("./") or url_str.startswith("../")):
        if allow_local_files:
            clean_path = url_str.replace("file://", "")
            if os.path.exists(clean_path):
                return True, "Valid local file"
            return False, f"Local image file not found on disk: '{clean_path}'. (If your spreadsheet contains Google Drive or web URLs, ensure the 'Photo Link' column is selected as the Image URL Column)."
        return False, "Local file access not permitted"

    try:
        parsed = urllib.parse.urlparse(url_str)
        if parsed.scheme.lower() not in ("http", "https"):
            return False, f"Unsupported protocol '{parsed.scheme}'. Only HTTP, HTTPS and local paths are permitted."

        hostname = parsed.hostname
        if not hostname:
            return False, "Missing hostname in URL"

        hostname_lower = hostname.lower()
        if hostname_lower in ("localhost", "127.0.0.1", "::1", "metadata.google.internal", "instance-data"):
            return False, "Access to localhost or cloud metadata services is blocked"

        # Resolve IP to check for private / internal addresses
        try:
            ip_info = socket.getaddrinfo(hostname, None)
            for item in ip_info:
                ip_str = item[4][0]
                ip_obj = ipaddress.ip_address(ip_str)
                for net in PRIVATE_NETWORKS:
                    if ip_obj in net:
                        return False, f"URL resolves to private network address ({ip_str})"
        except socket.gaierror:
            pass

        return True, "Valid URL format"

    except Exception as e:
        return False, f"Invalid URL syntax: {str(e)}"


def normalize_google_drive_url(url: str) -> str:
    """
    Converts various Google Drive share URLs to direct download links.
    e.g. https://drive.google.com/file/d/XYZ/view -> https://drive.google.com/uc?export=download&id=XYZ
    """
    s = str(url).strip()
    m = re.search(r'drive\.google\.com/(?:file/d/|open\?id=|uc\?id=)([a-zA-Z0-9_-]+)', s)
    if m:
        fid = m.group(1)
        return f"https://drive.google.com/uc?export=download&id={fid}"
    return s


def read_tabular_file(file_path: str) -> Tuple[List[str], List[List[Any]]]:
    """
    Reads CSV or Excel (.xlsx/.xls) spreadsheet.
    Returns (headers, rows).
    """
    ext = os.path.splitext(file_path)[1].lower()
    headers = []
    rows = []

    if ext in ('.xlsx', '.xls'):
        wb = openpyxl.load_workbook(file_path, data_only=True)
        ws = wb.active
        
        # Detect header row
        header_row_idx = 1
        for r in range(1, min(10, ws.max_row + 1)):
            non_empty = [c for c in range(1, ws.max_column + 1) if ws.cell(r, c).value is not None]
            if len(non_empty) >= 1:
                header_row_idx = r
                break

        headers = [str(ws.cell(header_row_idx, c).value or f"Col_{c}").strip() for c in range(1, ws.max_column + 1)]
        
        for r in range(header_row_idx + 1, ws.max_row + 1):
            row_vals = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
            if any(v is not None and str(v).strip() != "" for v in row_vals):
                rows.append(row_vals)
    else:
        # CSV with encoding fallback
        encodings = ['utf-8-sig', 'utf-8', 'cp1252', 'latin1']
        parsed_ok = False
        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc, errors='replace') as f:
                    sample = f.read(4096)
                    f.seek(0)
                    dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|') if sample.strip() else 'excel'
                    reader = list(csv.reader(f, dialect=dialect))
                    if reader:
                        headers = [str(h).strip() if str(h).strip() else f"Col_{i+1}" for i, h in enumerate(reader[0])]
                        rows = [r for r in reader[1:] if any(str(c).strip() for c in r)]
                        parsed_ok = True
                        break
            except Exception:
                continue

        if not parsed_ok:
            raise ValueError(f"Could not parse file '{os.path.basename(file_path)}' with supported encodings.")

    return headers, rows


def detect_columns(headers: List[str], rows: List[List[Any]]) -> Dict[str, Optional[int]]:
    """
    Intelligently detects:
      - url_col: column containing image URL or photo link
      - id_col: column containing Image ID / Serial No
      - date_col: column containing existing or target date
      - time_col: column containing timestamp
    """
    result = {
        "url_col": None,
        "id_col": None,
        "date_col": None,
        "time_col": None
    }

    # 1. Detect URL Column: Score each column by both actual cell contents and header keywords
    best_url_col = None
    best_url_score = -9999

    for idx, h in enumerate(headers):
        h_lower = str(h).lower().strip()
        score = 0

        # Sample first 20 non-empty values
        sample_vals = [str(r[idx]).strip() for r in rows[:20] if idx < len(r) and r[idx] is not None]
        http_count = sum(1 for v in sample_vals if v.startswith('http://') or v.startswith('https://') or 'drive.google.com' in v)
        path_count = sum(1 for v in sample_vals if any(v.lower().endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.webp')))

        # Heavy weight for actual working HTTP/Drive links
        if http_count > 0:
            score += 200 * (http_count / max(1, len(sample_vals)))
        elif path_count > 0:
            score += 40 * (path_count / max(1, len(sample_vals)))

        # Header match scoring
        if 'photo link' in h_lower or 'image link' in h_lower or 'drive link' in h_lower or 'photo url' in h_lower or 'image url' in h_lower:
            score += 100
        elif 'link' in h_lower or 'url' in h_lower:
            score += 60
        elif 'photo' in h_lower or 'image' in h_lower:
            score += 20

        # Penalty if header is clearly just a path or folder description when another column has URLs
        if 'location' in h_lower or 'path' in h_lower:
            score -= 30

        if score > best_url_score:
            best_url_score = score
            best_url_col = idx

    result["url_col"] = best_url_col if best_url_col is not None else 0

    # 2. Detect ID Column
    id_keywords = ['image id', 'photo id', 'id', 'sl no', 'sl.no', 'serial no', 'asset id', 'pole id', 'barcode', 'code']
    for idx, h in enumerate(headers):
        if idx == result["url_col"]:
            continue
        h_lower = str(h).lower().strip()
        for kw in id_keywords:
            if kw == h_lower or kw in h_lower:
                result["id_col"] = idx
                break
        if result["id_col"] is not None:
            break

    # 3. Detect Date / Time Column
    date_keywords = ['target date', 'updated date', 'date', 'survey date']
    for idx, h in enumerate(headers):
        if idx in (result["url_col"], result["id_col"]):
            continue
        h_lower = str(h).lower().strip()
        for kw in date_keywords:
            if kw in h_lower:
                result["date_col"] = idx
                break
        if result["date_col"] is not None:
            break

    time_keywords = ['timestamp', 'time', 'photo time', 'capture time']
    for idx, h in enumerate(headers):
        if idx in (result["url_col"], result["id_col"]):
            continue
        h_lower = str(h).lower().strip()
        for kw in time_keywords:
            if kw in h_lower:
                result["time_col"] = idx
                break
        if result["time_col"] is not None:
            break

    return result


def inspect_and_validate_dataset(
    headers: List[str],
    rows: List[List[Any]],
    url_col: int,
    id_col: Optional[int] = None,
    date_col: Optional[int] = None
) -> Dict[str, Any]:
    """
    Validates all rows in the dataset:
    - Normalizes URLs
    - Checks SSRF / safety
    - Identifies duplicates
    - Extracts ID
    - Returns structured summary
    """
    url_seen = {}
    validated_items = []
    valid_count = 0
    duplicate_count = 0
    invalid_count = 0

    for idx, r in enumerate(rows):
        row_num = idx + 1
        raw_url = str(r[url_col]).strip() if url_col < len(r) and r[url_col] is not None else ""
        norm_url = normalize_google_drive_url(raw_url)

        # ID extraction
        if id_col is not None and id_col < len(r) and r[id_col] is not None and str(r[id_col]).strip():
            img_id = str(r[id_col]).strip()
        else:
            img_id = f"IMG_{row_num:04d}"

        # Custom date extraction
        custom_date_val = str(r[date_col]).strip() if date_col is not None and date_col < len(r) and r[date_col] is not None else ""

        is_safe, safety_reason = is_safe_url(norm_url)
        is_duplicate = False

        if norm_url:
            if norm_url in url_seen:
                is_duplicate = True
                duplicate_count += 1
                duplicate_of = url_seen[norm_url]
            else:
                url_seen[norm_url] = row_num
                duplicate_of = None
        else:
            duplicate_of = None

        if not raw_url:
            status = "empty_url"
            error_msg = "Row is missing an image URL"
            invalid_count += 1
        elif not is_safe:
            status = "invalid_url"
            error_msg = safety_reason
            invalid_count += 1
        elif is_duplicate:
            status = "duplicate"
            error_msg = f"Duplicate of Row {duplicate_of}"
            valid_count += 1 # Valid syntax, duplicate
        else:
            status = "ready"
            error_msg = ""
            valid_count += 1

        validated_items.append({
            "row_id": row_num,
            "image_id": img_id,
            "original_url": raw_url,
            "normalized_url": norm_url,
            "custom_date": custom_date_val,
            "status": status,
            "is_duplicate": is_duplicate,
            "duplicate_of": duplicate_of,
            "error_message": error_msg,
            "raw_row": [str(c) if c is not None else "" for c in r]
        })

    return {
        "total_rows": len(rows),
        "valid_count": valid_count,
        "duplicate_count": duplicate_count,
        "invalid_count": invalid_count,
        "items": validated_items
    }


def create_dataset_from_local_photo_records(photo_records: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Creates an offline-ready survey dataset directly from local photo files
    without requiring any spreadsheet.
    """
    validated_items = []
    headers = ["Image ID", "Photo Filename", "File Path", "Status"]
    rows = []

    for idx, rec in enumerate(photo_records, start=1):
        filename = rec.get("filename", f"photo_{idx}.jpg")
        local_path = rec.get("path", "")
        img_id = os.path.splitext(filename)[0] or f"IMG_{idx:04d}"

        validated_items.append({
            "row_id": idx,
            "image_id": img_id,
            "original_url": local_path,
            "normalized_url": local_path,
            "custom_date": "",
            "status": "ready",
            "is_duplicate": False,
            "duplicate_of": None,
            "error_message": "",
            "raw_row": [img_id, filename, local_path, "Ready"]
        })
        rows.append([img_id, filename, local_path, "Ready"])

    validation_result = {
        "total_rows": len(validated_items),
        "valid_count": len(validated_items),
        "duplicate_count": 0,
        "invalid_count": 0,
        "items": validated_items
    }

    return {
        "headers": headers,
        "rows": rows,
        "url_col": 2, # File Path
        "id_col": 0,  # Image ID
        "date_col": None,
        "validation_result": validation_result
    }

