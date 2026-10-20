"""
Build script to compile GPS Stamp Date Changer Pro into a standalone Windows executable.
Run this script to generate a portable desktop application that runs on ANY Windows PC.
"""

import os
import sys
import shutil
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def build_standalone():
    print("==================================================")
    print("   Building GPS Stamp Date Changer Pro Executable ")
    print("==================================================")

    # PyInstaller arguments
    pyinstaller_cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed", # No CMD popup
        "--name", "GPS_Stamp_Date_Changer_Pro",
        "--add-data", f"{os.path.join(BASE_DIR, 'static')};static",
        "--add-data", f"{os.path.join(BASE_DIR, 'samples')};samples",
        "--add-data", f"{os.path.join(BASE_DIR, 'Roboto-Regular.ttf')};.",
        "--add-data", f"{os.path.join(BASE_DIR, 'Roboto-Medium.ttf')};.",
        "--collect-all", "rapidocr_onnxruntime",
        "--collect-all", "onnxruntime",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespans",
        "--hidden-import", "uvicorn.lifespans.on",
        "--hidden-import", "engine",
        "--hidden-import", "importer",
        "--hidden-import", "date_engine",
        "--hidden-import", "batch_processor",
        "--hidden-import", "reporter",
        "--hidden-import", "openpyxl",
        "--hidden-import", "docx",
        "--hidden-import", "rapidocr_onnxruntime",
        "--hidden-import", "onnxruntime",
        os.path.join(BASE_DIR, "desktop_app.py")
    ]

    print("\nRunning PyInstaller packaging...")
    result = subprocess.run(pyinstaller_cmd, cwd=BASE_DIR)
    
    if result.returncode == 0:
        dist_folder = os.path.join(BASE_DIR, "dist", "GPS_Stamp_Date_Changer_Pro")
        print("\n==================================================")
        print(" [SUCCESS] Standalone Application Built Successfully!")
        print(f" Output Location: {dist_folder}")
        print(" Executable: GPS_Stamp_Date_Changer_Pro.exe")
        print(" You can distribute this entire folder to ANY Windows computer!")
        print("==================================================")
        
        # Package into zip
        zip_output = os.path.join(BASE_DIR, "GPS_Stamp_Date_Changer_Pro_Windows_Portable")
        print(f"Creating portable ZIP archive: {zip_output}.zip ...")
        shutil.make_archive(zip_output, 'zip', dist_folder)
        print(f"[SUCCESS] Portable zip ready: {zip_output}.zip")
    else:
        print("\n[ERROR] Build process failed. See logs above.")

if __name__ == "__main__":
    build_standalone()
