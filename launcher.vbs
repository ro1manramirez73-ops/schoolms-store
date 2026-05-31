Dim oShell, oFSO, installDir, python, wsgiScript, localIP

Set oFSO   = CreateObject("Scripting.FileSystemObject")
Set oShell = CreateObject("WScript.Shell")

installDir = oFSO.GetParentFolderName(WScript.ScriptFullName)
python     = installDir & "\.python\pythonw.exe"
wsgiScript = installDir & "\wsgi.py"

If Not oFSO.FileExists(python) Then
    MsgBox "Python environment not found." & vbCrLf & vbCrLf & _
           "Please run setup_env.bat first, or re-run the installer.", _
           vbCritical, "School Management System"
    WScript.Quit
End If

' Get LAN IP for sharing with other computers on the network
On Error Resume Next
localIP = oShell.Exec( _
    "powershell -NoProfile -Command ""(Get-NetIPAddress -AddressFamily IPv4 | " & _
    "Where-Object { $_.PrefixOrigin -eq 'Dhcp' -or $_.PrefixOrigin -eq 'Manual' } | " & _
    "Select-Object -First 1).IPAddress""").StdOut.ReadAll()
On Error GoTo 0
localIP = Trim(localIP)
If localIP = "" Then localIP = "your-server-ip"

' Launch Flask server silently (no console window)
oShell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & wsgiScript & Chr(34), 0, False

' Wait for server to start then open browser
WScript.Sleep 3000
oShell.Run "http://localhost:5000", 1, False

MsgBox "School Management System is running!" & vbCrLf & vbCrLf & _
       "This computer  :  http://localhost:5000" & vbCrLf & _
       "Other devices  :  http://" & localIP & ":5000" & vbCrLf & vbCrLf & _
       "Share the second address with staff on the same Wi-Fi/network." & vbCrLf & vbCrLf & _
       "To stop the server: open Task Manager and end 'pythonw.exe'.", _
       vbInformation, "School Management System"
