"""
Automated Unit and Integration Tests for GPS Stamp Date Changer Pro
Tests date calculation, weekday accuracy, SSRF security, image editing, and report generation.
"""

import os
import unittest
from datetime import datetime
import numpy as np
import cv2

from date_engine import (
    parse_date_string,
    get_weekday_name,
    generate_date_range,
    assign_dates,
    get_distribution_statistics
)
from importer import (
    is_safe_url,
    sanitize_url_for_logging,
    normalize_google_drive_url,
    read_tabular_file,
    detect_columns,
    inspect_and_validate_dataset
)
from engine import process_gps_image, clean_and_replace_stamp_text, detect_map_camera_elements
from reporter import generate_excel_report, generate_csv_report, build_zip_package

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(BASE_DIR, "samples")


class TestDateEngine(unittest.TestCase):

    def test_weekday_calculation(self):
        """Test 1: Verify exact weekday calculation (never guessed)."""
        test_cases = [
            ("24/09/2026", "Thursday"),
            ("25/09/2026", "Friday"),
            ("26/09/2026", "Saturday"),
            ("27/09/2026", "Sunday"),
            ("28/09/2026", "Monday"),
            ("29/09/2026", "Tuesday"),
            ("30/09/2026", "Wednesday"),
            ("14/10/2026", "Wednesday"),
        ]
        for d_str, expected_day in test_cases:
            dt = parse_date_string(d_str)
            self.assertIsNotNone(dt, f"Failed to parse {d_str}")
            self.assertEqual(get_weekday_name(dt), expected_day)

    def test_date_range_validation(self):
        """Verify that From Date later than To Date raises ValueError."""
        with self.assertRaises(ValueError):
            assign_dates(
                total_images=10,
                start_date_str="14/10/2026",
                end_date_str="24/09/2026"
            )

    def test_mode_a_sequential_dates(self):
        """Test Mode A: Sequential date assignment and cycling."""
        assignments = assign_dates(
            total_images=5,
            start_date_str="24/09/2026",
            end_date_str="26/09/2026", # 3 days: 24, 25, 26
            mode="sequential",
            overflow_policy="cycle"
        )
        self.assertEqual(len(assignments), 5)
        self.assertEqual(assignments[0]["date_str"], "24/09/2026")
        self.assertEqual(assignments[0]["weekday"], "Thursday")
        self.assertEqual(assignments[1]["date_str"], "25/09/2026")
        self.assertEqual(assignments[1]["weekday"], "Friday")
        self.assertEqual(assignments[2]["date_str"], "26/09/2026")
        self.assertEqual(assignments[2]["weekday"], "Saturday")
        # Cycle back
        self.assertEqual(assignments[3]["date_str"], "24/09/2026")
        self.assertEqual(assignments[4]["date_str"], "25/09/2026")

    def test_mode_b_even_distribution(self):
        """Test Mode B: Even distribution of images across dates."""
        assignments = assign_dates(
            total_images=21,
            start_date_str="24/09/2026",
            end_date_str="30/09/2026", # 7 days
            mode="even_distribution"
        )
        self.assertEqual(len(assignments), 21)
        stats = get_distribution_statistics(assignments)
        self.assertEqual(stats["unique_dates_assigned"], 7)
        self.assertAlmostEqual(stats["avg_per_date"], 3.0, delta=0.5)

    def test_mode_c_custom_dates(self):
        """Test Mode C: Custom date assignment from spreadsheet list."""
        custom_dates = ["24/09/2026", "24/09/2026", "25/09/2026"]
        assignments = assign_dates(
            total_images=3,
            start_date_str="24/09/2026",
            end_date_str="30/09/2026",
            mode="custom",
            custom_dates=custom_dates
        )
        self.assertEqual(assignments[0]["date_str"], "24/09/2026")
        self.assertEqual(assignments[1]["date_str"], "24/09/2026")
        self.assertEqual(assignments[2]["date_str"], "25/09/2026")


class TestImporterAndSecurity(unittest.TestCase):

    def test_ssrf_blocking(self):
        """Verify that private addresses, localhost, and metadata endpoints are blocked."""
        blocked_urls = [
            "http://127.0.0.1:8080/secret.jpg",
            "http://localhost/admin/photo.png",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.5/photo.jpg",
            "http://192.168.1.1/cam.jpg",
            "ftp://example.com/test.jpg"
        ]
        for url in blocked_urls:
            is_safe, reason = is_safe_url(url)
            self.assertFalse(is_safe, f"Expected {url} to be blocked, but was allowed. Reason: {reason}")

    def test_safe_urls(self):
        """Verify that valid public HTTP/HTTPS URLs and local files are allowed."""
        safe_urls = [
            "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb",
            "https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OIv524M1Y/view"
        ]
        for url in safe_urls:
            is_safe, reason = is_safe_url(url)
            self.assertTrue(is_safe, f"Expected {url} to be allowed, reason: {reason}")

    def test_url_sanitization(self):
        """Verify that secret tokens are masked in logs and reports."""
        sensitive_url = "https://storage.googleapis.com/bucket/img.jpg?token=Secret12345&auth=BearerXYZ&id=10"
        clean = sanitize_url_for_logging(sensitive_url)
        self.assertNotIn("Secret12345", clean)
        self.assertNotIn("BearerXYZ", clean)
        self.assertIn("id=10", clean)

    def test_spreadsheet_reading_and_column_detection(self):
        """Verify that sample Excel can be parsed and columns detected."""
        xlsx_path = os.path.join(SAMPLES_DIR, "sample_field_survey.xlsx")
        self.assertTrue(os.path.exists(xlsx_path))
        headers, rows = read_tabular_file(xlsx_path)
        self.assertGreater(len(headers), 0)
        self.assertGreater(len(rows), 0)
        cols = detect_columns(headers, rows)
        self.assertIsNotNone(cols["url_col"])


class TestImageEditingAndPreservation(unittest.TestCase):

    def test_stamp_processing_and_pixel_preservation(self):
        """Verify that GPS stamp is updated while the rest of the scene remains untouched."""
        sample_img = os.path.join(SAMPLES_DIR, "IMG001.jpg")
        self.assertTrue(os.path.exists(sample_img))

        out_img = os.path.join(SAMPLES_DIR, "test_IMG001_edited.jpg")
        target_dt = datetime(2026, 9, 24, 15, 40) # 24/09/2026 is Thursday

        res = process_gps_image(
            input_image_path_or_array=sample_img,
            output_image_path=out_img,
            target_datetime=target_dt
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["assigned_weekday"], "Thursday")
        self.assertEqual(res["assigned_date"], "24/09/2026")
        self.assertTrue(os.path.exists(out_img))

        # Pixel Preservation Verification:
        # Check upper 50% of the image (pole, streetlights, sky).
        orig = cv2.imread(sample_img)
        edited = cv2.imread(out_img)
        self.assertEqual(orig.shape, edited.shape)

        h, w = orig.shape[:2]
        scene_orig = orig[0:int(h * 0.50), :]
        scene_edited = edited[0:int(h * 0.50), :]

        diff = cv2.absdiff(scene_orig, scene_edited)
        max_diff = np.max(diff)
        # Due to lossy JPEG DCT quantization upon file write, small difference (<15) is expected,
        # but macro-structure is strictly preserved.
        self.assertLessEqual(max_diff, 15, "Photographic scene in upper 50% was visibly modified!")

        # Also test lossless in-memory / PNG array
        out_png = os.path.join(SAMPLES_DIR, "test_IMG001_edited.png")
        sample_png = os.path.join(SAMPLES_DIR, "test_IMG001.png")
        cv2.imwrite(sample_png, orig)
        process_gps_image(sample_png, out_png, target_dt)
        png_orig = cv2.imread(sample_png)
        png_edited = cv2.imread(out_png)
        png_diff = np.max(cv2.absdiff(png_orig[0:int(h * 0.50), :], png_edited[0:int(h * 0.50), :]))
        self.assertEqual(png_diff, 0, "Lossless pixel preservation was not exactly 0!")


if __name__ == "__main__":
    unittest.main()
