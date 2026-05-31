# Creates a Blairwood Academy desktop shortcut on this machine.
# Run once from the project root: powershell -ExecutionPolicy Bypass -File create_shortcut.ps1

$projectDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$pythonw      = Join-Path $projectDir ".venv\Scripts\pythonw.exe"
$launcher     = Join-Path $projectDir "launcher.pyw"
$ico          = Join-Path $projectDir "files (1)\static\icons\bwa_logo_uGU_1.ico"
$desktop      = [System.Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop "Blairwood Academy.lnk"

# Fall back to system pythonw / python if no venv
if (-not (Test-Path $pythonw)) {
    $pythonw = Join-Path $projectDir ".venv\Scripts\python.exe"
}
if (-not (Test-Path $pythonw)) {
    $found = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($found) { $pythonw = $found.Source }
}
if (-not (Test-Path $pythonw)) {
    $found = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($found) { $pythonw = $found.Source }
}
if (-not (Test-Path $pythonw)) {
    Write-Error "Python not found. Install Python 3.8+ and re-run this script."
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$lnk   = $shell.CreateShortcut($shortcutPath)
$lnk.TargetPath       = $pythonw
$lnk.Arguments        = "`"$launcher`""
$lnk.WorkingDirectory = $projectDir
$lnk.Description      = "Blairwood Academy School Management System"
if (Test-Path $ico) { $lnk.IconLocation = $ico }
$lnk.Save()

Write-Host ""
Write-Host "Desktop shortcut created successfully!" -ForegroundColor Green
Write-Host "  Location : $shortcutPath" -ForegroundColor Cyan
Write-Host "  Launcher : $launcher" -ForegroundColor Cyan
Write-Host "  Python   : $pythonw" -ForegroundColor Cyan
Write-Host ""
Write-Host "Double-click 'Blairwood Academy' on your desktop to launch the app." -ForegroundColor Yellow
