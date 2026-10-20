# GPS Stamp Date Changer Pro

**GPS Stamp Date Changer Pro** is a high-performance, local-first desktop and web application designed for field survey, utility inspection, and infrastructure engineering teams. It allows users to batch-update the visible weekday and calendar date displayed in GPS Map Camera-style photo overlays from an Excel or CSV file, while preserving the original photograph, coordinates, location address, map preview, branding, time, and timezone.

---

## 🚀 Key Features

- **100% Scene & Stamp Preservation**:
  - Preserves streetlight poles, electrical panels, utility infrastructure, wires, buildings, and sky.
  - Preserves GPS Map Camera branding, coordinates (`Lat / Long`), address text, and map preview inset.
  - Preserves capture time (hour, minute, AM/PM) and timezone (e.g., `GMT +05:30`).
  - Genuine image-processing engine using OpenCV inpainting and PIL anti-aliased font rendering (no generative AI hallucination).
- **Variable Weekday Length Handling**:
  - Dynamically calculates font layout so long day names (e.g., `Wednesday` vs `Monday`) fit cleanly within the text region without overlapping coordinates or the satellite map inset.
- **Automated Weekday Calculation**:
  - Automatically calculates the correct day of the week for every assigned date using Python's calendar library (never guessed or assumed).
- **Date Assignment Modes**:
  - **Mode A: Sequential Dates**: Assigns dates sequentially starting from *From Date* to *To Date*. Supports overflow policies: *Cycle Range*, *Evenly Distribute*, or *Stop Assigning*.
  - **Mode B: Even Distribution**: Distributes hundreds or thousands of photos evenly across the calendar date range.
  - **Mode C: Custom Target Dates**: Reads specific per-photo target dates directly from a spreadsheet column.
  - **Mode D: Preserve Existing Dates**: Keeps existing dates for designated records and updates only chosen rows.
- **Robust Spreadsheet & URL Importer**:
  - Supports Excel (`.xlsx`, `.xls`) and CSV (`.csv`).
  - Auto-detects URL, ID, and Date columns with manual override dropdowns.
  - Supports Google Drive links (`drive.google.com/file/d/...`), direct HTTP/HTTPS URLs, and local file paths.
  - Pre-validates links and detects duplicate URLs.
- **Enterprise Security (SSRF Protection)**:
  - Blocks requests to loopback (`127.0.0.1`, `localhost`), private subnets (`10.0.0.0/8`, `192.168.0.0/16`, `172.16.0.0/12`), and cloud metadata endpoints (`169.254.169.254`).
  - Masks sensitive tokens, passwords, and query parameters in logs and exported reports.
- **Interactive Batch Processing & Inspection**:
  - Side-by-side zoomable visual inspection of sample images before running the full batch.
  - Live progress tracking with current image number, elapsed time, and ETA.
  - Live control buttons: **Pause**, **Resume**, **Cancel**, and **Retry Failed**.
  - Manual review and adjustment modal for low-confidence or custom-stamped images.
- **Comprehensive Audit Exports**:
  - Formatted Excel audit report (`.xlsx`) with status badges.
  - Standard CSV audit report (`.csv`).
  - Failed records spreadsheet for quick re-importing.
  - Full ZIP archive containing all processed photos with customizable file naming (`{ImageID}_{DD-MM-YYYY}.jpg` or original filename).

---

## 🛠️ Quick Start on Windows

### Option 1: One-Click Startup (Recommended)
Simply double-click:
```bat
run_app.bat
```
This launcher automatically:
1. Detects your Python runtime.
2. Verifies and installs missing dependencies.
3. Generates sample demonstration data if needed.
4. Starts the local server and opens `http://127.0.0.1:8000` in your web browser.

---

### Option 2: Manual Terminal Launch

1. **Verify Python 3.10+**:
   ```powershell
   python --version
   ```

2. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

3. **Generate Sample Data (Optional)**:
   ```powershell
   python generate_samples.py
   ```

4. **Start the Application**:
   ```powershell
   python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
   ```

5. **Open Browser**:
   Navigate to [http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## 📋 Step-by-Step Workflow Guide

### Step 1: Upload Survey Spreadsheet
1. Drag and drop your Excel or CSV file onto the dropzone.
2. The system automatically detects the **Photo URL** and **Image ID** columns.
3. Review the validation summary banner (valid rows, duplicates, syntax errors).

### Step 2: Configure Date Range & Assignment Rule
1. Pick **From Date** and **To Date** using the calendar pickers.
2. Select your desired Date Assignment Mode:
   - *Sequential Dates* (with Cycle or Distribute overflow rule)
   - *Even Distribution*
   - *Custom Dates*
   - *Preserve Existing Dates*
3. Click **Preview Date Sequence** to view the calculated calendar statistics (total calendar days, unique dates, average photos per day) and the proposed date assignments.

### Step 3: Verify Stamp Visual Quality
1. Click **Preview Stamp** on any row to generate an instant side-by-side comparison of the original photo and the proposed updated GPS stamp.
2. Inspect the overlay text alignment, font matching, and coordinate preservation.

### Step 4: Run Batch Processing
1. Click **Start Full Batch Processing**.
2. Monitor real-time progress: completed count, remaining count, current file, and ETA.
3. Use **Pause**, **Resume**, or **Cancel** at any time.

### Step 5: Download Results & Audit Reports
1. **Download Individual Photo**: Click the download button on any completed row.
2. **Download Full ZIP**: Download all processed images packaged with the audit report.
3. **Audit Excel / CSV**: Download the complete report containing Image ID, original URL, assigned date/day, detected timestamp, and processing status.
4. **Retry Failed**: Click to automatically re-queue any failed or flagged items.

---

## 🧪 Automated Test Suite

A complete unit and integration test suite is included in `tests/test_suite.py`.

Run tests:
```powershell
python -m unittest tests/test_suite.py
```

### Test Coverage:
- **Test 1**: Sequential date assignment and weekday calculation.
- **Test 2**: Even distribution across calendar date ranges.
- **Test 3**: Custom spreadsheet date mapping.
- **Test 4**: Date validation (From Date <= To Date).
- **Test 5**: SSRF protection (blocking localhost, private IP subnets, and cloud metadata).
- **Test 6**: URL token sanitization for privacy.
- **Test 7**: GPS stamp overlay recognition and date text replacement.
- **Test 8**: Photographic scene pixel preservation (bit-for-bit preservation of poles, wires, sky, and map inset).

---

## 🔒 Security & Privacy

- **No Cloud API Dependency**: Runs 100% locally on your machine.
- **SSRF Hardened**: All URLs are validated against private IP ranges and loopback destinations before requests are dispatched.
- **Credential Protection**: Private API tokens, passwords, and sensitive query strings are masked in logs and exported audit spreadsheets.
- **Sanitized Filenames**: Output file names are sanitized against path traversal and illegal filesystem characters.

---

## 📂 Project Structure

```text
GPS_Stamp_Studio_Cloud_Package/
├── app.py                 # FastAPI server and REST endpoints
├── batch_processor.py     # Multi-threaded download and image editing pipeline
├── date_engine.py         # Date range generator, weekday calculator, and assignment modes
├── engine.py              # OpenCV + PIL GPS Map Camera recognition and editing engine
├── importer.py            # Spreadsheet reader, SSRF security validator, and duplicate tracker
├── reporter.py            # Formatted Excel (.xlsx), CSV, and ZIP export generator
├── generate_samples.py    # Synthetic realistic field photo and survey spreadsheet generator
├── requirements.txt       # Python dependencies
├── run_app.bat            # One-click Windows application launcher
├── samples/               # Sample test images and spreadsheets
├── static/
│   └── index.html         # Responsive web dashboard interface
└── tests/
    └── test_suite.py      # Automated unit and integration test suite
```
