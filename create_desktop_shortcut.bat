@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "TARGET_VBS=%SCRIPT_DIR%Launch_Desktop_App.vbs"
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\GPS Stamp Date Changer Pro.lnk"

echo Creating desktop shortcut...

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = 'wscript.exe'; $s.Arguments = '\"%TARGET_VBS%\"'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.Description = 'GPS Stamp Date Changer Pro'; $s.Save()"

if exist "%SHORTCUT_PATH%" (
    echo [OK] Shortcut created successfully on your Desktop:
    echo "%SHORTCUT_PATH%"
) else (
    echo [ERROR] Failed to create shortcut.
)
pause
