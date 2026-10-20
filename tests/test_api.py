"""
End-to-End API Integration Test for GPS Stamp Date Changer Pro
Simulates user uploading a spreadsheet, configuring dates, inspecting previews,
running a batch, and downloading reports.
"""

import os
import time
import unittest
from fastapi.testclient import TestClient
from app import app

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES_DIR = os.path.join(BASE_DIR, "samples")


class TestAPIEndpoints(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_index_and_health(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("GPS Stamp Date Changer Pro", resp.text)

        resp_health = self.client.get("/api/health")
        self.assertEqual(resp_health.status_code, 200)
        self.assertEqual(resp_health.json()["status"], "ok")

    def test_02_upload_and_date_preview(self):
        xlsx_path = os.path.join(SAMPLES_DIR, "sample_field_survey.xlsx")
        self.assertTrue(os.path.exists(xlsx_path))

        with open(xlsx_path, "rb") as f:
            resp = self.client.post("/api/upload", files={"file": ("sample_survey.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("upload_id", data)
        self.assertEqual(data["summary"]["total"], 5)
        upload_id = data["upload_id"]

        # Date preview
        preview_resp = self.client.post("/api/date-preview", json={
            "upload_id": upload_id,
            "start_date": "2026-09-24",
            "end_date": "2026-10-14",
            "mode": "sequential",
            "overflow_policy": "cycle"
        })
        self.assertEqual(preview_resp.status_code, 200)
        preview_data = preview_resp.json()
        self.assertEqual(preview_data["total_images"], 5)
        self.assertEqual(preview_data["preview_sequence"][0]["assigned_weekday"], "Thursday")
        self.assertEqual(preview_data["preview_sequence"][0]["assigned_date"], "24/09/2026")

        # Single stamp preview
        sample_resp = self.client.post("/api/preview-stamp", json={
            "upload_id": upload_id,
            "row_id": 1,
            "target_date": "24/09/2026",
            "clean_level": "standard"
        })
        self.assertEqual(sample_resp.status_code, 200)
        sample_data = sample_resp.json()
        self.assertTrue(sample_data["success"])
        self.assertIn("raw_image_url", sample_data)
        self.assertIn("edited_image_url", sample_data)

    def test_03_batch_execution_and_exports(self):
        xlsx_path = os.path.join(SAMPLES_DIR, "sample_field_survey.xlsx")
        with open(xlsx_path, "rb") as f:
            resp = self.client.post("/api/upload", files={"file": ("survey.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        upload_id = resp.json()["upload_id"]

        # Start batch
        start_resp = self.client.post("/api/start-batch", json={
            "upload_id": upload_id,
            "start_date": "2026-09-24",
            "end_date": "2026-09-28",
            "mode": "sequential",
            "overflow_policy": "cycle",
            "naming_rule": "id_date",
            "preserve_time": True,
            "clean_level": "standard"
        })
        self.assertEqual(start_resp.status_code, 200)
        job_id = start_resp.json()["job_id"]

        # Poll until complete (timeout 40 seconds)
        for _ in range(80):
            status_resp = self.client.get(f"/api/job/{job_id}/status")
            self.assertEqual(status_resp.status_code, 200)
            status_data = status_resp.json()
            if status_data["progress"]["state"] in ("completed", "cancelled", "error"):
                break
            time.sleep(0.5)

        self.assertEqual(status_data["progress"]["state"], "completed")
        self.assertEqual(status_data["progress"]["succeeded"], 5)

        # Test Excel download
        excel_resp = self.client.get(f"/api/job/{job_id}/export-excel")
        self.assertEqual(excel_resp.status_code, 200)
        self.assertGreater(len(excel_resp.content), 1000)

        # Test CSV download
        csv_resp = self.client.get(f"/api/job/{job_id}/export-csv")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("Image ID,Original URL,Assigned Date", csv_resp.text)

        # Test ZIP download
        zip_resp = self.client.get(f"/api/job/{job_id}/download-zip")
        self.assertEqual(zip_resp.status_code, 200)
        self.assertGreater(len(zip_resp.content), 2000)


if __name__ == "__main__":
    unittest.main()
