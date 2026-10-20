"""
Generates synthetic, realistic GPS Map Camera field survey photographs
and sample Excel/CSV spreadsheets for testing and demonstration.
"""

import os
import cv2
import numpy as np
import openpyxl
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLES_DIR = os.path.join(BASE_DIR, "samples")
os.makedirs(SAMPLES_DIR, exist_ok=True)

FONT_DIR = "C:/Windows/Fonts" if os.path.exists("C:/Windows/Fonts") else "/usr/share/fonts"

def get_font(size: int, bold: bool = False):
    font_file = "segoeuib.ttf" if bold else "segoeui.ttf"
    p = os.path.join(FONT_DIR, font_file)
    if os.path.exists(p):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

def create_gps_field_photo(
    out_path: str,
    city: str = "Guwahati, Assam, India",
    address: str = "GS Road, Dispur, Guwahati, Kamrup, Assam 781005",
    lat_lon: str = "Lat 26.144518° Long 91.736236°",
    timestamp_str: str = "Monday, 08/06/2026 03:40 PM GMT +05:30",
    width: int = 1280,
    height: int = 960
):
    """Draws a realistic field photograph with utility pole and GPS Map Camera card overlay."""
    # 1. Base photographic scene (sky gradient, road, ground, streetlight pole)
    img = np.zeros((height, width, 3), dtype=np.uint8)
    
    # Sky gradient
    for y in range(int(height * 0.65)):
        ratio = y / (height * 0.65)
        # Deep sky blue to light horizon
        b = int(220 - 40 * ratio)
        g = int(180 - 30 * ratio)
        r = int(120 - 40 * ratio)
        img[y, :] = (b, g, r)

    # Ground / road
    for y in range(int(height * 0.65), height):
        ratio = (y - height * 0.65) / (height * 0.35)
        b = int(70 + 20 * ratio)
        g = int(80 + 20 * ratio)
        r = int(75 + 20 * ratio)
        img[y, :] = (b, g, r)

    # Streetlight utility pole
    pole_x = int(width * 0.42)
    cv2.rectangle(img, (pole_x - 12, int(height * 0.20)), (pole_x + 12, int(height * 0.85)), (90, 95, 100), -1)
    cv2.rectangle(img, (pole_x - 14, int(height * 0.20)), (pole_x + 14, int(height * 0.22)), (60, 65, 70), -1)
    
    # Streetlight luminaire arm
    cv2.line(img, (pole_x, int(height * 0.22)), (pole_x + 120, int(height * 0.16)), (80, 85, 90), 8)
    cv2.ellipse(img, (pole_x + 130, int(height * 0.16)), (25, 10), 0, 0, 360, (230, 230, 240), -1)

    # Electrical junction panel on pole
    cv2.rectangle(img, (pole_x - 22, int(height * 0.48)), (pole_x + 22, int(height * 0.62)), (180, 185, 190), -1)
    cv2.rectangle(img, (pole_x - 22, int(height * 0.48)), (pole_x + 22, int(height * 0.62)), (50, 50, 50), 2)
    # Cable conduit
    cv2.line(img, (pole_x, int(height * 0.62)), (pole_x, int(height * 0.85)), (40, 40, 40), 4)

    # Convert to PIL for anti-aliased card overlay & typography
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil_im = Image.fromarray(img_rgb)
    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)

    # 2. Semi-transparent black card banner
    card_h = int(height * 0.22)
    card_y = height - card_h
    # 60% opacity dark banner
    draw_ov.rectangle([(0, card_y), (width, height)], fill=(15, 23, 42, 175))

    # 3. Map Inset (Square on right side)
    map_size = int(card_h * 0.85)
    map_x = int(width * 0.74)
    map_y = card_y + int((card_h - map_size) / 2)
    
    # Map background (satellite green/khaki with road grid)
    draw_ov.rectangle([(map_x, map_y), (map_x + map_size, map_y + map_size)], fill=(70, 90, 80, 255), outline=(255, 255, 255, 200), width=2)
    # Grid roads
    draw_ov.line([(map_x + int(map_size * 0.3), map_y), (map_x + int(map_size * 0.3), map_y + map_size)], fill=(220, 220, 200, 200), width=3)
    draw_ov.line([(map_x, map_y + int(map_size * 0.5)), (map_x + map_size, map_y + int(map_size * 0.5))], fill=(240, 210, 100, 230), width=4)
    # Map pin
    pin_cx = map_x + int(map_size * 0.3)
    pin_cy = map_y + int(map_size * 0.5)
    draw_ov.ellipse([(pin_cx - 8, pin_cy - 16), (pin_cx + 8, pin_cy)], fill=(239, 68, 68, 255))
    # Google logo tag
    f_google = get_font(max(9, int(width * 0.010)), bold=True)
    draw_ov.text((map_x + 5, map_y + map_size - 14), "Google", fill=(255, 255, 255, 230), font=f_google)

    # 4. Text Overlay on Left
    f_title = get_font(int(width * 0.024), bold=True)
    f_body = get_font(int(width * 0.021), bold=False)

    text_x = int(width * 0.04)
    line_spacing = int(height * 0.042)
    
    # Line 1: City
    draw_ov.text((text_x, card_y + int(card_h * 0.12)), city, fill=(255, 255, 255, 255), font=f_title)
    # Line 2: Address
    draw_ov.text((text_x, card_y + int(card_h * 0.12) + line_spacing), address, fill=(240, 240, 240, 255), font=f_body)
    # Line 3: Lat Long
    draw_ov.text((text_x, card_y + int(card_h * 0.12) + line_spacing * 2), lat_lon, fill=(240, 240, 240, 255), font=f_body)
    # Line 4: Timestamp (Date, Time, Weekday, GMT)
    draw_ov.text((text_x, card_y + int(card_h * 0.12) + line_spacing * 3), timestamp_str, fill=(255, 255, 255, 255), font=f_body)

    # Merge alpha
    final_im = Image.alpha_composite(pil_im.convert('RGBA'), overlay)
    final_im.convert('RGB').save(out_path, quality=98)


def generate_all_samples():
    """Generates 5 realistic sample images and accompanying Excel/CSV spreadsheets."""
    samples = [
        ("IMG001.jpg", "Monday, 08/06/2026 09:15 AM GMT +05:30", "Lat 26.144518° Long 91.736236°"),
        ("IMG002.jpg", "Monday, 08/06/2026 11:30 AM GMT +05:30", "Lat 26.147220° Long 91.740110°"),
        ("IMG003.jpg", "Monday, 08/06/2026 01:45 PM GMT +05:30", "Lat 26.150310° Long 91.745500°"),
        ("IMG004.jpg", "Monday, 08/06/2026 03:40 PM GMT +05:30", "Lat 26.158400° Long 91.771200°"),
        ("IMG005.jpg", "Monday, 08/06/2026 05:20 PM GMT +05:30", "Lat 26.162100° Long 91.780300°"),
    ]

    image_records = []
    for fname, ts, coords in samples:
        fpath = os.path.join(SAMPLES_DIR, fname)
        create_gps_field_photo(fpath, timestamp_str=ts, lat_lon=coords)
        image_records.append((fname, fpath, ts))
        print(f"Generated sample photo: {fpath}")

    # Generate sample Excel spreadsheet
    xlsx_path = os.path.join(SAMPLES_DIR, "sample_field_survey.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Survey Photos"
    
    ws.append(["Image ID", "Photo URL", "Existing Date", "Asset Description", "GPS Location"])
    for idx, (fname, fpath, ts) in enumerate(image_records, start=1):
        ws.append([
            f"POLE_{idx:03d}",
            fpath, # Local file path supported directly
            "08/06/2026",
            f"Smart LED Streetlight Pole #{idx:03d}",
            "Guwahati Smart City Ward 4"
        ])
    wb.save(xlsx_path)
    print(f"Generated sample Excel: {xlsx_path}")

    # Generate sample CSV spreadsheet
    csv_path = os.path.join(SAMPLES_DIR, "sample_field_survey.csv")
    import csv
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["Image ID", "Photo URL", "Existing Date", "Asset Description", "GPS Location"])
        for idx, (fname, fpath, ts) in enumerate(image_records, start=1):
            w.writerow([
                f"POLE_{idx:03d}",
                fpath,
                "08/06/2026",
                f"Smart LED Streetlight Pole #{idx:03d}",
                "Guwahati Smart City Ward 4"
            ])
    print(f"Generated sample CSV: {csv_path}")

if __name__ == "__main__":
    generate_all_samples()
