Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

strCurDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Check if standalone exe exists
strExe = strCurDir & "\dist\GPS_Stamp_Date_Changer_Pro\GPS_Stamp_Date_Changer_Pro.exe"

If fso.FileExists(strExe) Then
    WshShell.CurrentDirectory = strCurDir & "\dist\GPS_Stamp_Date_Changer_Pro"
    WshShell.Run """" & strExe & """", 1, False
Else
    ' Fallback to Python runner
    strPy = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe")
    If Not fso.FileExists(strPy) Then
        strPy = "pythonw"
    End If
    WshShell.CurrentDirectory = strCurDir
    WshShell.Run """" & strPy & """ """ & strCurDir & "\desktop_app.py""", 0, False
End If
