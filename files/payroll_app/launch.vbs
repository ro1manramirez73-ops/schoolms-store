Set WShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Start Streamlit in background (no CMD window)
WShell.Run "cmd /c cd /d """ & appDir & """ && py -3.13 -m streamlit run app.py --server.address=localhost --server.port=8501", 0, False

' Wait 3 seconds for server to start, then open browser
WScript.Sleep 3000
WShell.Run "http://localhost:8501"
