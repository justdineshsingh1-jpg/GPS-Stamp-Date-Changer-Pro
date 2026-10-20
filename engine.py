"""
GPS Stamp Date Changer Pro - Recognition & High-Fidelity Editing Engine
Preserves 100% of the original photo scene, coordinates, address, map preview,
and updates only the visible weekday and calendar date in the GPS overlay.
"""

import os
import re
import cv2
import numpy as np
from datetime import datetime, timedelta
from typing import Tuple, Dict, Any, Optional
from PIL import Image, ImageFont, ImageDraw, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
FONT_DIR = "C:/Windows/Fonts" if os.path.exists("C:/Windows/Fonts") else "/usr/share/fonts"

# Try importing RapidOCR
try:
    from rapidocr_onnxruntime import RapidOCR
    RAPID_OCR = RapidOCR()
    HAS_RAPID_OCR = True
except Exception:
    RAPID_OCR = None
    HAS_RAPID_OCR = False

# Try importing pytesseract
try:
    import pytesseract
    # Check common Windows paths for Tesseract binary if not on PATH
    for t_path in [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")
    ]:
        if os.path.exists(t_path):
            pytesseract.pytesseract.tesseract_cmd = t_path
            break
    HAS_PYTESSERACT = True
except Exception:
    HAS_PYTESSERACT = False


def clean_time_and_tz(raw_text: str) -> Tuple[str, str]:
    """Extracts and normalizes existing time and timezone preserving original layout."""
    m_time = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)?', raw_text, re.IGNORECASE)
    if m_time:
        hh = m_time.group(1).zfill(2)
        mm = m_time.group(2)
        ampm = m_time.group(3)
        if not ampm:
            m_ampm = re.search(r'(AM|PM)', raw_text, re.IGNORECASE)
            ampm = m_ampm.group(1).upper() if m_ampm else 'PM'
        else:
            ampm = ampm.upper()
        time_str = f"{hh}:{mm} {ampm}"
    else:
        time_str = "12:00 PM"
        
    has_plus = bool(re.search(r'\+\d{2}:\d{2}', raw_text))
    if has_plus:
        m_offset = re.search(r'\+(\d{2}):(\d{2})', raw_text)
        offset_str = f"+{m_offset.group(1)}:{m_offset.group(2)}" if m_offset else "+05:30"
        tz_str = f"GMT {offset_str}"
    else:
        tz_str = "GMT"
        
    return time_str, tz_str


def load_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    """Loads a TrueType font with graceful fallback to system sans-serif fonts."""
    local_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(local_dir, "Roboto-Regular.ttf"),
        os.path.join(FONT_DIR, f"{font_name}.ttf"),
        os.path.join(FONT_DIR, f"{font_name}b.ttf"),
        os.path.join(FONT_DIR, "arial.ttf"),
        os.path.join(FONT_DIR, "segoeui.ttf"),
        os.path.join(FONT_DIR, "tahoma.ttf"),
        os.path.join(FONT_DIR, "calibri.ttf"),
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def extract_time_from_text_or_filename(text: Any) -> Tuple[int, int, int]:
    """Extracts hour, minute, second from timestamp string, filename or ISO datetime."""
    if not text:
        return 12, 0, 0
    
    text_str = str(text).strip()
    
    # 1. Check HH:MM:SS AM/PM or HH:MM AM/PM
    m_ampm = re.search(r'(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)', text_str, re.IGNORECASE)
    if m_ampm:
        h = int(m_ampm.group(1))
        m = int(m_ampm.group(2))
        s = int(m_ampm.group(3)) if m_ampm.group(3) else 0
        ampm = m_ampm.group(4).upper()
        if ampm == 'PM' and h < 12:
            h += 12
        elif ampm == 'AM' and h == 12:
            h = 0
        return h, m, s

    # 2. Check 24-hr format HH:MM:SS or HH:MM
    m_24 = re.search(r'(?:^|\s)(\d{2}):(\d{2})(?::(\d{2}))?(?:\s|$)', text_str)
    if m_24:
        h = int(m_24.group(1))
        m = int(m_24.group(2))
        s = int(m_24.group(3)) if m_24.group(3) else 0
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m, s

    # 3. Check filename pattern like 2026-09-24_15-40-10
    m_fn = re.search(r'[-_](\d{2})[-:](\d{2})[-:](\d{2})', text_str)
    if m_fn:
        return int(m_fn.group(1)), int(m_fn.group(2)), int(m_fn.group(3))

    return 12, 0, 0


def detect_map_camera_elements(img_bgr: np.ndarray) -> Dict[str, Any]:
    """
    Analyzes the photograph to locate:
    - GPS overlay card bounding box
    - Map preview position (left, right, or none)
    - Latitude/Longitude anchor location
    - Existing timestamp line position and extracted strings
    - Font size and font family estimation
    - Card opacity and background color
    """
    h, w = img_bgr.shape[:2]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # High-precision OCR detection using RapidOCR if available
    if HAS_RAPID_OCR and RAPID_OCR is not None:
        try:
            offset_y = int(h * 0.55)
            ocr_results, _ = RAPID_OCR(img_bgr[offset_y:, :])
            if ocr_results:
                date_line_item = None
                for item in ocr_results:
                    txt = item[1].replace(' ', '')
                    if re.search(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun).*\d{2}/\d{2}/\d{4}', txt, re.IGNORECASE) or re.search(r'\d{2}/\d{2}/\d{4}.*(?:AM|PM)', txt, re.IGNORECASE):
                        date_line_item = item
                        break
                
                if date_line_item:
                    raw_text = date_line_item[1]
                    box = date_line_item[0]
                    conf = float(date_line_item[2])
                    x1 = int(min(pt[0] for pt in box))
                    y1 = int(min(pt[1] for pt in box) + offset_y)
                    x2 = int(max(pt[0] for pt in box))
                    y2 = int(max(pt[1] for pt in box) + offset_y)
                    box_h = y2 - y1
                    
                    time_str, tz_str = clean_time_and_tz(raw_text)
                    detected_day = None
                    for day in DAYS:
                        if day.lower() in raw_text.lower():
                            detected_day = day
                            break
                            
                    font_sz = max(10, int(box_h * 0.90))
                    # Map position detection: if original text extends past 82% of width, map is on the left
                    if x2 > int(w * 0.82):
                        map_side = "left"
                        x_safe_max = int(w * 0.98)
                    else:
                        map_side = "right"
                        x_safe_max = max(x2 + 15, int(w * 0.78))
                    
                    # Extract date string if present
                    m_d = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})', raw_text)
                    ext_date = m_d.group(1).replace('-', '/') if m_d else None
                    
                    return {
                        "has_stamp": True,
                        "confidence": conf,
                        "layout_type": "day_single_line" if detected_day else "single_line",
                        "font_size": font_sz,
                        "font_name": "arial",
                        "lat_loc": (x1, y1),
                        "date_y": y1,
                        "x_safe_max": x_safe_max,
                        "gmt_loc": None,
                        "detected_day": detected_day,
                        "extracted_time": time_str,
                        "extracted_tz": tz_str,
                        "extracted_date": ext_date,
                        "ocr_box": (x1, y1, x2, y2),
                        "box_h": box_h,
                    }
        except Exception:
            pass

    # GPS stamp fallback template matching (located in bottom 45% of photo)
    bottom_y_start = int(h * 0.55)
    bottom_roi = gray[bottom_y_start:h, :]
    
    # 1. Detect Lat anchor
    min_sz = max(10, int(w * 0.014))
    max_sz = max(24, int(w * 0.038))
    step_sz = max(1, int(w * 0.002))

    best_lat_score = -1.0
    best_lat_loc = None
    best_font_sz = int(w * 0.024)
    best_font_name = "segoeui"

    for font_name in ['segoeui', 'arial']:
        for sz in range(min_sz, max_sz, step_sz):
            f = load_font(font_name, sz)
            tpl_im = Image.new('L', (int(sz * 2.5), int(sz * 1.5)), 0)
            d = ImageDraw.Draw(tpl_im)
            d.text((2, 2), 'Lat', fill=255, font=f)
            arr = np.array(tpl_im)
            pts = np.where(arr > 0)
            if len(pts[0]) == 0: continue
            tight = arr[pts[0].min():pts[0].max()+1, pts[1].min():pts[1].max()+1]
            if bottom_roi.shape[0] < tight.shape[0] or bottom_roi.shape[1] < tight.shape[1]: continue
            
            res = cv2.matchTemplate(bottom_roi, tight, cv2.TM_CCOEFF_NORMED)
            min_v, max_v, min_l, max_l = cv2.minMaxLoc(res)
            if max_v > best_lat_score:
                best_lat_score = float(max_v)
                best_lat_loc = (max_l[0], bottom_y_start + max_l[1])
                best_font_sz = sz
                best_font_name = font_name

    has_valid_stamp = (best_lat_score >= 0.42 and best_lat_loc is not None)

    if not has_valid_stamp:
        # Fallback heuristic anchor: standard bottom-left position
        lat_x = int(w * 0.05)
        lat_y = int(h * 0.88)
        font_sz = int(w * 0.024)
        font_name = "segoeui"
        confidence = float(max(0.0, best_lat_score))
    else:
        lat_x, lat_y = best_lat_loc
        font_sz = best_font_sz
        font_name = best_font_name
        confidence = float(best_lat_score)

    # 2. Detect map inset boundary
    # In standard GPS Map Camera, map is situated on right (e.g. from x ~ 0.70*w to 0.98*w)
    # Safe text region ends at x_safe_max
    map_side = "right"
    x_safe_max = int(w * 0.71) # Never draw past this into the map inset!
    if lat_x > int(w * 0.35):
        # Map on left, text on right
        map_side = "left"
        x_safe_max = int(w * 0.98)

    # 3. Check for GMT anchor
    gmt_y_start = max(0, lat_y - int(font_sz * 0.5))
    gmt_y_end = min(h, lat_y + int(font_sz * 4.0))
    gmt_roi = gray[gmt_y_start:gmt_y_end, :]
    
    best_gmt_score = -1.0
    best_gmt_loc = None
    if gmt_roi.shape[0] > font_sz and gmt_roi.shape[1] > font_sz * 3:
        for s in (font_sz - 2, font_sz, font_sz + 2):
            f = load_font(font_name, s)
            tpl_im = Image.new('L', (int(s * 3.5), int(s * 1.5)), 0)
            d = ImageDraw.Draw(tpl_im)
            d.text((2, 2), 'GMT', fill=255, font=f)
            arr = np.array(tpl_im)
            pts = np.where(arr > 0)
            if len(pts[0]) == 0: continue
            tight = arr[pts[0].min():pts[0].max()+1, pts[1].min():pts[1].max()+1]
            if gmt_roi.shape[0] < tight.shape[0] or gmt_roi.shape[1] < tight.shape[1]: continue
            res = cv2.matchTemplate(gmt_roi, tight, cv2.TM_CCOEFF_NORMED)
            _, max_v, _, max_l = cv2.minMaxLoc(res)
            if max_v > best_gmt_score:
                best_gmt_score = float(max_v)
                best_gmt_loc = (max_l[0], gmt_y_start + max_l[1])

    # 4. Check for Day Name anchor below Lat
    detected_day = None
    day_y_start = lat_y + int(font_sz * 0.6)
    day_y_end = min(h, lat_y + int(font_sz * 3.5))
    day_x_start = max(0, lat_x - int(font_sz * 0.5))
    day_x_end = min(w, lat_x + int(font_sz * 10))
    
    day_roi = gray[day_y_start:day_y_end, day_x_start:day_x_end]
    best_day_score = -1.0
    if day_roi.shape[0] > font_sz and day_roi.shape[1] > font_sz * 2:
        for day in DAYS:
            f = load_font(font_name, font_sz)
            tpl_im = Image.new('L', (int(font_sz * len(day) * 0.7), int(font_sz * 1.5)), 0)
            d = ImageDraw.Draw(tpl_im)
            d.text((2, 2), day, fill=255, font=f)
            arr = np.array(tpl_im)
            pts = np.where(arr > 0)
            if len(pts[0]) == 0: continue
            tight = arr[pts[0].min():pts[0].max()+1, pts[1].min():pts[1].max()+1]
            if day_roi.shape[0] < tight.shape[0] or day_roi.shape[1] < tight.shape[1]: continue
            res = cv2.matchTemplate(day_roi, tight, cv2.TM_CCOEFF_NORMED)
            _, max_v, _, _ = cv2.minMaxLoc(res)
            if max_v > best_day_score:
                best_day_score = float(max_v)
                if max_v > 0.42:
                    detected_day = day

    # Layout type classification
    if detected_day:
        layout_type = "day_single_line"
    elif best_gmt_score > 0.52 and best_gmt_loc and best_gmt_loc[0] > (lat_x + font_sz * 12):
        layout_type = "split_gmt"
    elif has_valid_stamp:
        layout_type = "single_line"
    else:
        layout_type = "no_stamp"

    # Date line baseline coordinate
    if best_gmt_loc and best_gmt_loc[1] > lat_y:
        date_y = best_gmt_loc[1]
    else:
        date_y = lat_y + int(font_sz * 1.25)

    # 5. Extract existing time and timezone via OCR or pattern search
    extracted_time_str = "12:00 PM"
    extracted_tz_str = "GMT +05:30"
    extracted_date_str = None

    # OCR extraction if pytesseract is available
    if HAS_PYTESSERACT:
        try:
            ocr_y1 = max(0, date_y - int(font_sz * 0.5))
            ocr_y2 = min(h, date_y + int(font_sz * 2.2))
            ocr_x1 = max(0, lat_x - int(font_sz * 0.5))
            ocr_x2 = min(w, x_safe_max + int(font_sz * 2))
            
            ocr_crop = gray[ocr_y1:ocr_y2, ocr_x1:ocr_x2]
            if ocr_crop.size > 0:
                # Contrast enhancement for clean OCR
                ocr_scaled = cv2.resize(ocr_crop, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                _, ocr_thresh = cv2.threshold(ocr_scaled, 180, 255, cv2.THRESH_BINARY)
                ocr_text = pytesseract.image_to_string(ocr_thresh, config='--psm 6')
                
                # Search time
                m_t = re.search(r'(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)', ocr_text, re.IGNORECASE)
                if m_t:
                    extracted_time_str = m_t.group(1).strip()

                # Search timezone
                m_tz = re.search(r'(GMT\s*[+-]?\s*\d{1,2}:\d{2})', ocr_text, re.IGNORECASE)
                if m_tz:
                    extracted_tz_str = m_tz.group(1).strip()

                # Search existing date
                m_d = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})', ocr_text)
                if m_d:
                    extracted_date_str = m_d.group(1).replace('-', '/')
        except Exception:
            pass

    return {
        "has_stamp": has_valid_stamp,
        "confidence": confidence,
        "layout_type": layout_type,
        "font_size": font_sz,
        "font_name": font_name,
        "lat_loc": (lat_x, lat_y),
        "date_y": date_y,
        "x_safe_max": x_safe_max,
        "gmt_loc": best_gmt_loc,
        "detected_day": detected_day,
        "extracted_time": extracted_time_str,
        "extracted_tz": extracted_tz_str,
        "extracted_date": extracted_date_str,
    }


def clean_and_replace_stamp_text(
    img_bgr: np.ndarray,
    target_dt: datetime,
    elements: Dict[str, Any],
    time_override: Optional[str] = None,
    tz_override: Optional[str] = None,
    font_size_override: Optional[int] = None,
    clean_level: str = "standard"
) -> Tuple[np.ndarray, str]:
    """
    Inpaints ONLY the date/day text area, matching background card alpha/color,
    and renders the updated weekday and date without touching map inset, coordinates or branding.
    """
    h, w = img_bgr.shape[:2]
    lat_x, lat_y = elements["lat_loc"]
    date_y = elements["date_y"]
    x_safe_max = elements["x_safe_max"]
    sz = font_size_override if (font_size_override and font_size_override >= 8) else elements["font_size"]
    font_name = elements["font_name"]
    layout_type = elements["layout_type"]

    day_name = target_dt.strftime('%A')
    date_str = target_dt.strftime('%d/%m/%Y')
    
    # Preserve original time or apply override
    time_str = time_override if time_override else elements.get("extracted_time", target_dt.strftime('%I:%M %p'))
    tz_str = tz_override if tz_override else elements.get("extracted_tz", "GMT +05:30")

    # Construct replacement string according to layout
    if layout_type == "day_single_line" or elements.get("detected_day"):
        full_text = f"{day_name}, {date_str} {time_str} {tz_str}"
    elif layout_type == "split_gmt":
        full_text = f"{date_str} {time_str}"
        gmt_text = tz_str
    else:
        full_text = f"{date_str} {time_str} {tz_str}"

    # Calculate precise font size so replacement never exceeds safe width (protecting map inset)
    font = load_font(font_name, sz)
    max_allowed_w = x_safe_max - lat_x
    
    # Measure width and adjust font size smoothly if weekday name is long (e.g. Wednesday)
    curr_sz = sz
    while curr_sz > 8:
        font = load_font(font_name, curr_sz)
        bbox = font.getbbox(full_text)
        text_w = bbox[2] - bbox[0]
        if text_w <= max_allowed_w:
            break
        curr_sz -= 1

    # Inpaint Bounding Box Isolation:
    # We inpaint only the narrow rectangle of the date line
    if "ocr_box" in elements:
        ox1, oy1, ox2, oy2 = elements["ocr_box"]
        y1 = max(0, oy1 - 2)
        y2 = min(h, oy2 + 3)
        x1 = max(0, ox1 - 2)
        x2 = min(w, max(ox2, ox1 + text_w) + 8)
        draw_y = oy1 - 1
    else:
        y1 = max(0, date_y - int(curr_sz * 0.35))
        y2 = min(h, date_y + int(curr_sz * 1.55))
        x1 = max(0, lat_x - int(curr_sz * 0.25))
        x2 = min(w, min(x_safe_max + 10, lat_x + int(max(text_w, curr_sz * 20) + curr_sz * 2)))
        draw_y = date_y

    # Inpaint mask creation
    strip = img_bgr[y1:y2, x1:x2]
    if strip.size > 0:
        strip_gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        thresh_val = 55 if clean_level == "deep_clean" else 70
        _, strip_thresh = cv2.threshold(strip_gray, thresh_val, 255, cv2.THRESH_BINARY)
        k_sz = max(3, int(curr_sz * 0.10))
        kernel = np.ones((k_sz, k_sz), np.uint8)
        dilated = cv2.dilate(strip_thresh, kernel, iterations=1)

        mask = np.zeros((h, w), dtype=np.uint8)
        mask[y1:y2, x1:x2] = dilated
        inpainted = cv2.inpaint(img_bgr, mask, inpaintRadius=max(2, int(curr_sz * 0.06)), flags=cv2.INPAINT_TELEA)
    else:
        inpainted = img_bgr.copy()

    # Redraw Typography with anti-aliasing on PIL
    img_rgb = cv2.cvtColor(inpainted, cv2.COLOR_BGR2RGB)
    pil_im = Image.fromarray(img_rgb)
    draw = ImageDraw.Draw(pil_im)

    if layout_type == "split_gmt":
        draw.text((lat_x, draw_y), full_text, fill=(255, 255, 255), font=font)
        gmt_x = elements["gmt_loc"][0] if elements["gmt_loc"] else int(w * 0.68)
        draw.text((gmt_x, draw_y), tz_str, fill=(255, 255, 255), font=font)
    else:
        draw.text((lat_x, draw_y), full_text, fill=(255, 255, 255), font=font)

    result_bgr = cv2.cvtColor(np.array(pil_im), cv2.COLOR_RGB2BGR)

    # Guarantee 100% bitwise pixel preservation of everything outside [y1:y2, x1:x2]
    final_bgr = img_bgr.copy()
    final_bgr[y1:y2, x1:x2] = result_bgr[y1:y2, x1:x2]

    detail_msg = f"Replaced with '{full_text}' ({font_name}, sz={curr_sz})"
    return final_bgr, detail_msg


def save_image(out_path: str, img_bgr: np.ndarray):
    dirname = os.path.dirname(out_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    ext = os.path.splitext(out_path)[1].lower()
    if ext == '.png':
        cv2.imwrite(out_path, img_bgr, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    else:
        cv2.imwrite(out_path, img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 98])


def process_gps_image(
    input_image_path_or_array,
    output_image_path: Optional[str],
    target_datetime: datetime,
    time_override: Optional[str] = None,
    tz_override: Optional[str] = None,
    layout_override: str = "auto",
    font_size_override: Optional[int] = None,
    font_family_override: str = "auto",
    clean_level: str = "standard"
) -> Dict[str, Any]:
    """
    Main entry point for processing a GPS-stamped photograph.
    Loads image, detects GPS stamp elements, replaces date & weekday,
    preserves original scene and all other overlay elements.
    """
    if isinstance(input_image_path_or_array, str):
        if not os.path.exists(input_image_path_or_array):
            return {
                "success": False,
                "error": f"Image file not found: {input_image_path_or_array}",
                "status": "failed",
                "detected_layout": "unknown",
                "confidence": 0.0
            }
        img_bgr = cv2.imread(input_image_path_or_array)
        if img_bgr is None:
            try:
                with Image.open(input_image_path_or_array) as pil_im:
                    img_bgr = cv2.cvtColor(np.array(pil_im.convert('RGB')), cv2.COLOR_RGB2BGR)
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to decode image: {str(e)}",
                    "status": "failed",
                    "detected_layout": "unknown",
                    "confidence": 0.0
                }
    else:
        img_bgr = input_image_path_or_array

    # Detect elements
    elements = detect_map_camera_elements(img_bgr)

    if layout_override != "auto":
        elements["layout_type"] = layout_override

    if font_family_override != "auto":
        elements["font_name"] = font_family_override

    # If no stamp detected or confidence is extremely low (<0.40)
    if not elements["has_stamp"] and layout_override == "auto":
        if output_image_path:
            save_image(output_image_path, img_bgr)
            
        return {
            "success": False,
            "status": "needs_review",
            "message": "No recognizable GPS Map Camera overlay detected. Preserved original image.",
            "detected_layout": "no_stamp",
            "confidence": elements["confidence"],
            "elements": elements
        }

    # Clean and replace
    try:
        edited_bgr, detail_msg = clean_and_replace_stamp_text(
            img_bgr=img_bgr,
            target_dt=target_datetime,
            elements=elements,
            time_override=time_override,
            tz_override=tz_override,
            font_size_override=font_size_override,
            clean_level=clean_level
        )

        if output_image_path:
            save_image(output_image_path, edited_bgr)

        return {
            "success": True,
            "status": "completed",
            "message": detail_msg,
            "detected_layout": elements["layout_type"],
            "confidence": elements["confidence"],
            "original_time": elements.get("extracted_time"),
            "original_tz": elements.get("extracted_tz"),
            "assigned_date": target_datetime.strftime("%d/%m/%Y"),
            "assigned_weekday": target_datetime.strftime("%A"),
            "elements": elements,
            "output_path": output_image_path
        }
    except Exception as e:
        return {
            "success": False,
            "status": "failed",
            "error": f"Editing error: {str(e)}",
            "detected_layout": elements.get("layout_type", "unknown"),
            "confidence": elements.get("confidence", 0.0)
        }
