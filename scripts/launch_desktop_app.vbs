' Silent wrapper so double-clicking the desktop shortcut doesn't flash a
' PowerShell console window - just opens the app window directly.
Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""C:\Users\bear1\Desktop\TrendSparC_MVP\scripts\launch_desktop_app.ps1""", 0, False
