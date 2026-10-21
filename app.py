"""
GPS Stamp Date Changer Pro - Main Application Server
FastAPI backend providing RESTful endpoints for:
- Spreadsheet import and intelligent column detection
- SSRF-safe URL validation and duplicate detection
- Deterministic date range sequence generation
- Single-image preview and interactive side-by-side comparison
- Resilient background batch processing with Pause/Resume/Cancel/Retry
- Audit reporting in Excel (.xlsx) and CSV (.csv) formats
- Individual and bulk ZIP exports
"""

import os
import shutil
import uuid
import threading
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from importer import read_tabular_file, detect_columns, inspect_and_validate_dataset, create_dataset_from_local_photo_records
from date_engine import assign_dates, get_distribution_statistics, parse_date_string
from engine import process_gps_image
from batch_processor import BatchJob, run_batch_pipeline
from reporter import generate_excel_report, generate_csv_report, generate_failed_records_report, build_zip_package

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
JOBS_DIR = os.path.join(BASE_DIR, "jobs")
SAMPLES_DIR = os.path.join(BASE_DIR, "samples")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(JOBS_DIR, exist_ok=True)
os.makedirs(SAMPLES_DIR, exist_ok=True)

app = FastAPI(
    title="GPS Stamp Date Changer Pro",
    description="Professional enterprise batch processor for updating visible dates in GPS-stamped photographs.",
    version="2.0.0"
)

# Mount static web assets
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# In-memory session tracking
UPLOADS_DATA: Dict[str, Dict[str, Any]] = {}
ACTIVE_JOBS: Dict[str, BatchJob] = {}


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>GPS Stamp Date Changer Pro is loading...</h1>")


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "GPS Stamp Date Changer Pro", "version": "2.0.0"}


# =========================================================================
# Step 1: Upload & Dataset Validation
# =========================================================================

@app.post("/api/upload")
async def upload_dataset(file: UploadFile = File(...)):
    """Uploads an Excel or CSV survey spreadsheet and auto-detects columns."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.xlsx', '.xls', '.csv'):
        raise HTTPException(status_code=400, detail="Unsupported format. Please upload an Excel (.xlsx, .xls) or CSV (.csv) file.")

    upload_id = str(uuid.uuid4())
    upload_folder = os.path.join(UPLOADS_DIR, upload_id)
    os.makedirs(upload_folder, exist_ok=True)

    file_path = os.path.join(upload_folder, file.filename)
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    try:
        headers, rows = read_tabular_file(file_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read spreadsheet: {str(e)}")

    if not rows:
        raise HTTPException(status_code=400, detail="The uploaded spreadsheet contains no data rows.")

    detected_cols = detect_columns(headers, rows)
    url_col = detected_cols["url_col"] if detected_cols["url_col"] is not None else 0
    id_col = detected_cols["id_col"]
    date_col = detected_cols["date_col"]

    validation_result = inspect_and_validate_dataset(
        headers=headers,
        rows=rows,
        url_col=url_col,
        id_col=id_col,
        date_col=date_col
    )

    UPLOADS_DATA[upload_id] = {
        "upload_id": upload_id,
        "filename": file.filename,
        "file_path": file_path,
        "headers": headers,
        "rows": rows,
        "url_col": url_col,
        "id_col": id_col,
        "date_col": date_col,
        "validation_result": validation_result
    }

    return {
        "upload_id": upload_id,
        "filename": file.filename,
        "total_rows": len(rows),
        "headers": headers,
        "detected_columns": detected_cols,
        "summary": {
            "total": validation_result["total_rows"],
            "valid": validation_result["valid_count"],
            "duplicates": validation_result["duplicate_count"],
            "invalid": validation_result["invalid_count"]
        },
        "preview_items": validation_result["items"][:10]
    }


@app.post("/api/upload-photos")
async def upload_photos_direct(files: List[UploadFile] = File(...)):
    """
    Offline-first direct photo import: allows users to select photos directly
    from their computer/camera/SD card without needing a spreadsheet or internet connection.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No photo files received.")

    upload_id = str(uuid.uuid4())
    upload_folder = os.path.join(UPLOADS_DIR, upload_id, "direct_photos")
    os.makedirs(upload_folder, exist_ok=True)

    photo_records = []
    for f in files:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext in ('.jpg', '.jpeg', '.png', '.webp'):
            safe_fname = os.path.basename(f.filename)
            save_path = os.path.join(upload_folder, safe_fname)
            with open(save_path, "wb") as out_f:
                content = await f.read()
                out_f.write(content)
            photo_records.append({"filename": safe_fname, "path": save_path})

    if not photo_records:
        raise HTTPException(status_code=400, detail="No valid JPG or PNG images found in selection.")

    ds = create_dataset_from_local_photo_records(photo_records)
    v_res = ds["validation_result"]

    UPLOADS_DATA[upload_id] = {
        "upload_id": upload_id,
        "filename": f"{len(photo_records)} Local Photos",
        "file_path": upload_folder,
        "headers": ds["headers"],
        "rows": ds["rows"],
        "url_col": ds["url_col"],
        "id_col": ds["id_col"],
        "date_col": ds["date_col"],
        "validation_result": v_res
    }

    return {
        "upload_id": upload_id,
        "filename": f"{len(photo_records)} Local Photos",
        "total_rows": len(photo_records),
        "headers": ds["headers"],
        "detected_columns": {"url_col": ds["url_col"], "id_col": ds["id_col"], "date_col": ds["date_col"]},
        "summary": {
            "total": v_res["total_rows"],
            "valid": v_res["valid_count"],
            "duplicates": v_res["duplicate_count"],
            "invalid": v_res["invalid_count"]
        },
        "preview_items": v_res["items"][:10]
    }


class ConfigureColumnsRequest(BaseModel):
    upload_id: str
    url_col: int
    id_col: Optional[int] = None
    date_col: Optional[int] = None


@app.post("/api/configure-columns")
async def configure_columns(req: ConfigureColumnsRequest):
    """Re-evaluates validation when the user overrides column selections."""
    if req.upload_id not in UPLOADS_DATA:
        raise HTTPException(status_code=404, detail="Upload session expired or not found")

    data = UPLOADS_DATA[req.upload_id]
    headers = data["headers"]
    rows = data["rows"]

    validation_result = inspect_and_validate_dataset(
        headers=headers,
        rows=rows,
        url_col=req.url_col,
        id_col=req.id_col,
        date_col=req.date_col
    )

    data["url_col"] = req.url_col
    data["id_col"] = req.id_col
    data["date_col"] = req.date_col
    data["validation_result"] = validation_result

    return {
        "upload_id": req.upload_id,
        "summary": {
            "total": validation_result["total_rows"],
            "valid": validation_result["valid_count"],
            "duplicates": validation_result["duplicate_count"],
            "invalid": validation_result["invalid_count"]
        },
        "preview_items": validation_result["items"][:10]
    }


# =========================================================================
# Step 2: Date Sequence Configuration & Preview
# =========================================================================

class DatePreviewRequest(BaseModel):
    upload_id: str
    start_date: str # DD/MM/YYYY or YYYY-MM-DD
    end_date: str
    mode: str = "sequential" # sequential, even_distribution, custom, preserve
    overflow_policy: str = "cycle" # cycle, stop, distribute


@app.post("/api/date-preview")
async def date_preview(req: DatePreviewRequest):
    """Generates a deterministic preview of assigned dates and distribution metrics."""
    if req.upload_id not in UPLOADS_DATA:
        raise HTTPException(status_code=404, detail="Upload session not found")

    data = UPLOADS_DATA[req.upload_id]
    items = data["validation_result"]["items"]
    total = len(items)

    custom_dates = [i.get("custom_date") for i in items]

    try:
        assignments = assign_dates(
            total_images=total,
            start_date_str=req.start_date,
            end_date_str=req.end_date,
            mode=req.mode,
            overflow_policy=req.overflow_policy,
            custom_dates=custom_dates
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    stats = get_distribution_statistics(assignments)

    preview_rows = []
    for idx in range(min(15, total)):
        item = items[idx]
        assign = assignments[idx]
        preview_rows.append({
            "row_id": item["row_id"],
            "image_id": item["image_id"],
            "original_url": item["original_url"],
            "assigned_date": assign["date_str"],
            "assigned_weekday": assign["weekday"],
            "mode_applied": assign["mode_applied"]
        })

    return {
        "total_images": total,
        "statistics": stats,
        "preview_sequence": preview_rows
    }


# =========================================================================
# Step 3: Single Stamp Preview (Side-by-Side Comparison)
# =========================================================================

class SampleStampRequest(BaseModel):
    upload_id: str
    row_id: int
    target_date: str # DD/MM/YYYY
    clean_level: str = "standard"


@app.post("/api/preview-stamp")
async def preview_stamp(req: SampleStampRequest):
    """
    Downloads and updates a single image for interactive side-by-side inspection
    before the user commits to running the full batch.
    """
    if req.upload_id not in UPLOADS_DATA:
        raise HTTPException(status_code=404, detail="Upload session not found")

    data = UPLOADS_DATA[req.upload_id]
    items = data["validation_result"]["items"]
    target_item = next((i for i in items if i["row_id"] == req.row_id), None)
    if not target_item:
        raise HTTPException(status_code=404, detail=f"Row {req.row_id} not found")

    preview_dir = os.path.join(UPLOADS_DIR, req.upload_id, "preview")
    os.makedirs(preview_dir, exist_ok=True)

    raw_path = os.path.join(preview_dir, f"sample_raw_{req.row_id}.jpg")
    out_path = os.path.join(preview_dir, f"sample_edited_{req.row_id}.jpg")

    # Download or copy sample
    from batch_processor import download_single_image
    success, msg = download_single_image(target_item["normalized_url"], raw_path)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to fetch sample image: {msg}")

    target_dt = parse_date_string(req.target_date)
    if not target_dt:
        target_dt = datetime.now()

    result = process_gps_image(
        input_image_path_or_array=raw_path,
        output_image_path=out_path,
        target_datetime=target_dt,
        clean_level=req.clean_level
    )

    return {
        "success": result["success"],
        "status": result["status"],
        "message": result.get("message", ""),
        "detected_layout": result.get("detected_layout", "unknown"),
        "confidence": result.get("confidence", 0.0),
        "assigned_date": target_dt.strftime("%d/%m/%Y"),
        "assigned_weekday": target_dt.strftime("%A"),
        "original_time": result.get("original_time", ""),
        "raw_image_url": f"/api/preview-image/{req.upload_id}/sample_raw_{req.row_id}.jpg",
        "edited_image_url": f"/api/preview-image/{req.upload_id}/sample_edited_{req.row_id}.jpg"
    }


@app.get("/api/preview-image/{upload_id}/{filename}")
async def serve_preview_image(upload_id: str, filename: str):
    p = os.path.join(UPLOADS_DIR, upload_id, "preview", filename)
    if os.path.exists(p):
        return FileResponse(p, filename=filename, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Preview image not found")


# =========================================================================
# Step 4: Batch Processing Execution & Real-Time Controls
# =========================================================================

class StartBatchRequest(BaseModel):
    upload_id: str
    start_date: str
    end_date: str
    mode: str = "sequential"
    overflow_policy: str = "cycle"
    naming_rule: str = "id_date" # id_date or original
    preserve_time: bool = True
    clean_level: str = "standard"


@app.post("/api/start-batch")
async def start_batch(req: StartBatchRequest, background_tasks: BackgroundTasks):
    """Initiates the concurrent bulk processing job in the background."""
    if req.upload_id not in UPLOADS_DATA:
        raise HTTPException(status_code=404, detail="Upload session not found")

    data = UPLOADS_DATA[req.upload_id]
    items = data["validation_result"]["items"]

    # Calculate date assignments
    custom_dates = [i.get("custom_date") for i in items]
    try:
        assignments = assign_dates(
            total_images=len(items),
            start_date_str=req.start_date,
            end_date_str=req.end_date,
            mode=req.mode,
            overflow_policy=req.overflow_policy,
            custom_dates=custom_dates
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    job_id = str(uuid.uuid4())
    job = BatchJob(job_id=job_id, base_jobs_dir=JOBS_DIR)
    ACTIVE_JOBS[job_id] = job

    # Launch background processing pipeline
    def worker_wrapper():
        run_batch_pipeline(
            job=job,
            validated_items=items,
            date_assignments=assignments,
            naming_rule=req.naming_rule,
            preserve_time=req.preserve_time,
            clean_level=req.clean_level
        )
        # Generate reports upon completion
        try:
            excel_path = os.path.join(job.job_dir, "GPS_Stamp_Audit_Report.xlsx")
            csv_path = os.path.join(job.job_dir, "GPS_Stamp_Audit_Report.csv")
            failed_path = os.path.join(job.job_dir, "Failed_Images_Reprocess.xlsx")

            generate_excel_report(job_id, job.items, excel_path)
            generate_csv_report(job_id, job.items, csv_path)
            generate_failed_records_report(job.items, failed_path)

            zip_path = build_zip_package(
                job_id=job_id,
                job_dir=job.job_dir,
                edited_dir=job.edited_dir,
                items=job.items,
                excel_path=excel_path,
                csv_path=csv_path
            )

            job.excel_report_path = excel_path
            job.csv_report_path = csv_path
            job.failed_report_path = failed_path
            job.zip_path = zip_path
        except Exception as e:
            job.error_message = f"Report packaging error: {str(e)}"

    thread = threading.Thread(target=worker_wrapper, daemon=True)
    thread.start()

    return {"job_id": job_id, "total": len(items), "state": "started"}


@app.get("/api/job/{job_id}/status")
async def get_job_status(job_id: str):
    """Returns real-time progress, live counts, current item, and completed items."""
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job = ACTIVE_JOBS[job_id]
    progress = job.get_progress_data()
    
    # Return items list with preview URLs
    items_summary = []
    for item in job.items:
        items_summary.append({
            "row_id": item["row_id"],
            "image_id": item["image_id"],
            "assigned_date": item.get("assigned_date", ""),
            "assigned_weekday": item.get("assigned_weekday", ""),
            "original_time": item.get("original_time", ""),
            "updated_timestamp": item.get("updated_timestamp", ""),
            "status": item["status"],
            "confidence": round(item.get("confidence", 0.0), 2),
            "edited_file": item.get("edited_file", ""),
            "error_message": item.get("error_message", ""),
            "raw_url": f"/api/job/{job_id}/image/raw/{item['raw_file']}" if os.path.exists(os.path.join(job.raw_dir, item['raw_file'])) else None,
            "edited_url": f"/api/job/{job_id}/image/edited/{item['edited_file']}" if os.path.exists(os.path.join(job.edited_dir, item['edited_file'])) else None,
        })

    return {
        "progress": progress,
        "items": items_summary
    }


@app.post("/api/job/{job_id}/pause")
async def pause_job(job_id: str):
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    ACTIVE_JOBS[job_id].pause()
    return {"status": "paused"}


@app.post("/api/job/{job_id}/resume")
async def resume_job(job_id: str):
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    ACTIVE_JOBS[job_id].resume()
    return {"status": "resumed"}


@app.post("/api/job/{job_id}/cancel")
async def cancel_job(job_id: str):
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    ACTIVE_JOBS[job_id].cancel()
    return {"status": "cancelled"}


@app.post("/api/job/{job_id}/retry-failed")
async def retry_failed(job_id: str):
    """Re-attempts processing for failed or needs_review items."""
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = ACTIVE_JOBS[job_id]
    failed_items = [i for i in job.items if i["status"] in ("failed", "needs_review")]
    if not failed_items:
        return {"retried": 0, "message": "No failed items to retry"}

    def retry_worker():
        for item in failed_items:
            raw_path = os.path.join(job.raw_dir, item["raw_file"])
            out_path = os.path.join(job.edited_dir, item["edited_file"])
            
            # Re-download if needed
            if not os.path.exists(raw_path):
                from batch_processor import download_single_image
                succ, _ = download_single_image(item["normalized_url"], raw_path)
                if not succ:
                    continue

            target_dt = item.get("date_dt") or datetime.now()
            res = process_gps_image(raw_path, out_path, target_dt)
            if res["success"]:
                item["status"] = "completed"
                item["original_time"] = res.get("original_time", "")
                item["updated_timestamp"] = f"{item['assigned_weekday']}, {item['assigned_date']} {item['original_time']}"
                item["error_message"] = ""
                with job.lock:
                    job.succeeded += 1
                    job.failed = max(0, job.failed - 1)
            else:
                item["error_message"] = res.get("error", "Processing failed")

        # Rebuild reports & zip package
        try:
            excel_path = os.path.join(job.job_dir, "GPS_Stamp_Audit_Report.xlsx")
            csv_path = os.path.join(job.job_dir, "GPS_Stamp_Audit_Report.csv")
            failed_path = os.path.join(job.job_dir, "Failed_Images_Reprocess.xlsx")
            generate_excel_report(job_id, job.items, excel_path)
            generate_csv_report(job_id, job.items, csv_path)
            generate_failed_records_report(job.items, failed_path)

            zip_path = build_zip_package(
                job_id=job_id,
                job_dir=job.job_dir,
                edited_dir=job.edited_dir,
                items=job.items,
                excel_path=excel_path,
                csv_path=csv_path
            )
            job.excel_report_path = excel_path
            job.csv_report_path = csv_path
            job.failed_report_path = failed_path
            job.zip_path = zip_path
        except Exception as e:
            job.error_message = f"Report packaging error: {str(e)}"

    thread = threading.Thread(target=retry_worker, daemon=True)
    thread.start()

    return {"retried": len(failed_items), "message": f"Retry worker started for {len(failed_items)} items."}


@app.post("/api/job/{job_id}/open-folder")
async def open_job_folder(job_id: str):
    """Opens the local output directory in Windows File Explorer."""
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = ACTIVE_JOBS[job_id]
    if os.path.exists(job.job_dir):
        try:
            import subprocess
            subprocess.Popen(f'explorer "{os.path.normpath(job.job_dir)}"')
            return {"success": True, "path": job.job_dir}
        except Exception as e:
            return {"success": False, "error": str(e)}
    raise HTTPException(status_code=404, detail="Job folder not found")


# =========================================================================
# Step 5: Manual Stamp Review / Override
# =========================================================================

class ManualEditRequest(BaseModel):
    job_id: str
    row_id: int
    target_date: str # DD/MM/YYYY
    target_time: Optional[str] = None
    target_tz: Optional[str] = None
    layout_override: str = "auto"
    clean_level: str = "standard"


@app.post("/api/job/manual-edit")
async def manual_edit_stamp(req: ManualEditRequest):
    """Allows manual correction and immediate re-application for a flagged image."""
    if req.job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job = ACTIVE_JOBS[req.job_id]
    item = next((i for i in job.items if i["row_id"] == req.row_id), None)
    if not item:
        raise HTTPException(status_code=404, detail=f"Row {req.row_id} not found")

    raw_path = os.path.join(job.raw_dir, item["raw_file"])
    out_path = os.path.join(job.edited_dir, item["edited_file"])

    target_dt = parse_date_string(req.target_date) or datetime.now()

    res = process_gps_image(
        input_image_path_or_array=raw_path,
        output_image_path=out_path,
        target_datetime=target_dt,
        time_override=req.target_time,
        tz_override=req.target_tz,
        layout_override=req.layout_override,
        clean_level=req.clean_level
    )

    if res["success"]:
        item["status"] = "completed"
        item["assigned_date"] = target_dt.strftime("%d/%m/%Y")
        item["assigned_weekday"] = target_dt.strftime("%A")
        item["original_time"] = req.target_time or res.get("original_time", "")
        item["updated_timestamp"] = f"{item['assigned_weekday']}, {item['assigned_date']} {item['original_time']}"
        item["error_message"] = "Manually verified & updated"
        with job.lock:
            job.succeeded += 1
            if job.needs_review > 0:
                job.needs_review -= 1

    return {
        "success": res["success"],
        "status": item["status"],
        "message": res.get("message", res.get("error", "")),
        "edited_url": f"/api/job/{req.job_id}/image/edited/{item['edited_file']}"
    }


# =========================================================================
# Step 6: Downloads & Audit Report Exports
# =========================================================================

@app.get("/api/job/{job_id}/image/{img_type}/{filename}")
async def serve_job_image(job_id: str, img_type: str, filename: str):
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = ACTIVE_JOBS[job_id]
    target_dir = job.edited_dir if img_type == "edited" else job.raw_dir
    file_p = os.path.join(target_dir, filename)
    if os.path.exists(file_p):
        return FileResponse(file_p)
    raise HTTPException(status_code=404, detail="Image file not found")


@app.get("/api/job/{job_id}/download-image/{row_id}")
async def download_single_image(job_id: str, row_id: int):
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = ACTIVE_JOBS[job_id]
    item = next((i for i in job.items if i["row_id"] == row_id), None)
    if not item or not item.get("edited_file"):
        raise HTTPException(status_code=404, detail="Item or edited image not found")
    
    file_p = os.path.join(job.edited_dir, item["edited_file"])
    if os.path.exists(file_p):
        return FileResponse(file_p, filename=item["edited_file"], media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="File on disk missing")


@app.post("/api/job/{job_id}/download-selected")
async def download_selected_images(job_id: str, row_ids: List[int]):
    """Packages and returns a ZIP archive containing only the selected photos."""
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = ACTIVE_JOBS[job_id]
    zip_path = build_zip_package(
        job_id=job_id,
        job_dir=job.job_dir,
        edited_dir=job.edited_dir,
        items=job.items,
        excel_path=job.excel_report_path,
        csv_path=job.csv_report_path,
        selected_row_ids=row_ids
    )
    return FileResponse(zip_path, filename="GPS_Stamp_Selected_Photos.zip", media_type="application/zip")


@app.get("/api/job/{job_id}/download-zip")
async def download_full_zip(job_id: str):
    """Downloads full package with all completed images and audit reports."""
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = ACTIVE_JOBS[job_id]
    
    if not job.zip_path or not os.path.exists(job.zip_path):
        job.zip_path = build_zip_package(
            job_id=job_id,
            job_dir=job.job_dir,
            edited_dir=job.edited_dir,
            items=job.items,
            excel_path=job.excel_report_path,
            csv_path=job.csv_report_path
        )

    return FileResponse(job.zip_path, filename="GPS_Stamp_Date_Changer_Package.zip", media_type="application/zip")


@app.get("/api/job/{job_id}/export-excel")
async def export_excel_report(job_id: str):
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = ACTIVE_JOBS[job_id]
    if not job.excel_report_path or not os.path.exists(job.excel_report_path):
        p = os.path.join(job.job_dir, "GPS_Stamp_Audit_Report.xlsx")
        generate_excel_report(job_id, job.items, p)
        job.excel_report_path = p
    return FileResponse(job.excel_report_path, filename="GPS_Stamp_Audit_Report.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/job/{job_id}/export-csv")
async def export_csv_report(job_id: str):
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = ACTIVE_JOBS[job_id]
    if not job.csv_report_path or not os.path.exists(job.csv_report_path):
        p = os.path.join(job.job_dir, "GPS_Stamp_Audit_Report.csv")
        generate_csv_report(job_id, job.items, p)
        job.csv_report_path = p
    return FileResponse(job.csv_report_path, filename="GPS_Stamp_Audit_Report.csv", media_type="text/csv")


@app.get("/api/job/{job_id}/export-failed")
async def export_failed_report(job_id: str):
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = ACTIVE_JOBS[job_id]
    if not job.failed_report_path or not os.path.exists(job.failed_report_path):
        p = os.path.join(job.job_dir, "Failed_Images_Reprocess.xlsx")
        generate_failed_records_report(job.items, p)
        job.failed_report_path = p
    return FileResponse(job.failed_report_path, filename="Failed_Images_Reprocess.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def get_user_downloads_dir() -> str:
    """Returns the Windows Downloads directory path."""
    try:
        import winreg
        sub_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
            downloads_guid = "{374DE290-123F-4565-9164-39C4925E467B}"
            val, _ = winreg.QueryValueEx(key, downloads_guid)
            expanded = os.path.expandvars(val)
            if os.path.exists(expanded):
                return expanded
    except Exception:
        pass
    p = os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(p, exist_ok=True)
    return p


def copy_to_downloads(src_file: str, target_filename: str) -> str:
    """Copies file directly into Windows Downloads folder and highlights in File Explorer."""
    downloads_dir = get_user_downloads_dir()
    base, ext = os.path.splitext(target_filename)
    dest_path = os.path.join(downloads_dir, target_filename)
    counter = 1
    while os.path.exists(dest_path):
        dest_path = os.path.join(downloads_dir, f"{base} ({counter}){ext}")
        counter += 1
    shutil.copy2(src_file, dest_path)
    try:
        import sys, subprocess
        if sys.platform == "win32":
            subprocess.Popen(f'explorer /select,"{os.path.normpath(dest_path)}"')
    except Exception:
        pass
    return dest_path


class SaveToDownloadsRequest(BaseModel):
    file_type: str  # 'zip', 'excel', 'csv', 'failed', 'image'
    row_id: Optional[int] = None


@app.post("/api/job/{job_id}/save-to-downloads")
async def save_job_file_to_downloads(job_id: str, req: SaveToDownloadsRequest):
    """
    Saves the requested output file directly into the user's Downloads folder
    and highlights it in Windows File Explorer.
    """
    if job_id not in ACTIVE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = ACTIVE_JOBS[job_id]

    src_path = None
    target_filename = None

    if req.file_type == "zip":
        if not job.zip_path or not os.path.exists(job.zip_path):
            job.zip_path = build_zip_package(
                job_id=job_id,
                job_dir=job.job_dir,
                edited_dir=job.edited_dir,
                items=job.items,
                excel_path=job.excel_report_path,
                csv_path=job.csv_report_path
            )
        src_path = job.zip_path
        target_filename = "GPS_Stamp_Date_Changer_Package.zip"

    elif req.file_type == "excel":
        if not job.excel_report_path or not os.path.exists(job.excel_report_path):
            p = os.path.join(job.job_dir, "GPS_Stamp_Audit_Report.xlsx")
            generate_excel_report(job_id, job.items, p)
            job.excel_report_path = p
        src_path = job.excel_report_path
        target_filename = "GPS_Stamp_Audit_Report.xlsx"

    elif req.file_type == "csv":
        if not job.csv_report_path or not os.path.exists(job.csv_report_path):
            p = os.path.join(job.job_dir, "GPS_Stamp_Audit_Report.csv")
            generate_csv_report(job_id, job.items, p)
            job.csv_report_path = p
        src_path = job.csv_report_path
        target_filename = "GPS_Stamp_Audit_Report.csv"

    elif req.file_type == "failed":
        if not job.failed_report_path or not os.path.exists(job.failed_report_path):
            p = os.path.join(job.job_dir, "Failed_Images_Reprocess.xlsx")
            generate_failed_records_report(job.items, p)
            job.failed_report_path = p
        src_path = job.failed_report_path
        target_filename = "Failed_Images_Reprocess.xlsx"

    elif req.file_type == "image":
        if req.row_id is None:
            raise HTTPException(status_code=400, detail="Missing row_id for image save")
        item = next((i for i in job.items if i["row_id"] == req.row_id), None)
        if not item or not item.get("edited_file"):
            raise HTTPException(status_code=404, detail="Item or edited file not found")
        src_path = os.path.join(job.edited_dir, item["edited_file"])
        target_filename = item["edited_file"]

    if not src_path or not os.path.exists(src_path):
        raise HTTPException(status_code=404, detail="File to save does not exist")

    dest_path = copy_to_downloads(src_path, target_filename)
    return {
        "success": True,
        "filename": os.path.basename(dest_path),
        "saved_path": dest_path,
        "size": os.path.getsize(dest_path)
    }


@app.post("/api/preview-image/{upload_id}/save-to-downloads")
async def save_sample_preview_to_downloads(upload_id: str):
    """Saves the Step 3 sample preview photo directly into the user's Downloads folder."""
    preview_dir = os.path.join(UPLOADS_DIR, upload_id, "preview")
    if not os.path.exists(preview_dir):
        raise HTTPException(status_code=404, detail="No preview images found")
    
    # Find latest sample_edited image
    edited_files = [f for f in os.listdir(preview_dir) if f.startswith("sample_edited_") and f.lower().endswith(('.jpg', '.png'))]
    if not edited_files:
        raise HTTPException(status_code=404, detail="No edited sample preview found")
    
    src_file = os.path.join(preview_dir, sorted(edited_files)[-1])
    target_name = f"GPS_Stamp_Sample_Preview_{upload_id[:8]}.jpg"
    dest_path = copy_to_downloads(src_file, target_name)
    return {
        "success": True,
        "filename": os.path.basename(dest_path),
        "saved_path": dest_path
    }


@app.get("/api/sample-files/{filename}")
async def get_sample_file(filename: str):
    safe_name = os.path.basename(filename)
    p = os.path.join(SAMPLES_DIR, safe_name)
    if os.path.exists(p):
        return FileResponse(p, filename=safe_name)
    raise HTTPException(status_code=404, detail="Sample file not found")
