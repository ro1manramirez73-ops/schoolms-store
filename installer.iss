; ============================================================
;  School Management System — Inno Setup Installer Script
;  Compile with Inno Setup 6.x: https://jrsoftware.org/isinfo.php
; ============================================================

[Setup]
AppName=School Management System
AppVersion=2.0
AppPublisher=SchoolMS
AppPublisherURL=mailto:ro1manramirez73@gmail.com
AppSupportURL=mailto:ro1manramirez73@gmail.com
AppUpdatesURL=mailto:ro1manramirez73@gmail.com
DefaultDirName={autopf}\SchoolMS
DefaultGroupName=School Management System
OutputDir=installer_output
OutputBaseFilename=SchoolMS_Setup_v2.0
SetupIconFile=files\static\icons\logoRP.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
MinVersion=10.0
DisableWelcomePage=no
LicenseFile=LICENSE.txt
UninstallDisplayName=School Management System
UninstallDisplayIcon={app}\app\static\icons\logoRP.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut";            GroupDescription: "Additional icons:"
Name: "firewall";    Description: "Allow through Windows Firewall (recommended for staff access on the network)"; GroupDescription: "Network:"

[Files]
; ── Core Flask application ────────────────────────────────────────────────────
Source: "files\app.py";                DestDir: "{app}\app";                          Flags: ignoreversion
Source: "files\license.py";            DestDir: "{app}\app";                          Flags: ignoreversion
Source: "files\payroll_routes.py";     DestDir: "{app}\app";                          Flags: ignoreversion
Source: "files\db.py";                 DestDir: "{app}\app";                          Flags: ignoreversion skipifsourcedoesntexist
Source: "files\clean_db_script.py";    DestDir: "{app}\app";                          Flags: ignoreversion skipifsourcedoesntexist
Source: "files\seed_db.py";            DestDir: "{app}\app";                          Flags: ignoreversion skipifsourcedoesntexist

; ── Templates ─────────────────────────────────────────────────────────────────
Source: "files\templates\*";           DestDir: "{app}\app\templates";                Flags: ignoreversion recursesubdirs createallsubdirs

; ── Static assets ─────────────────────────────────────────────────────────────
Source: "files\static\*";             DestDir: "{app}\app\static";                   Flags: ignoreversion recursesubdirs createallsubdirs

; ── Payroll data layer (PDF generation + DB + Excel import) ───────────────────
Source: "files\payroll_app\db.py";          DestDir: "{app}\app\payroll_app";         Flags: ignoreversion
Source: "files\payroll_app\pdf_gen.py";     DestDir: "{app}\app\payroll_app";         Flags: ignoreversion
Source: "files\payroll_app\migrate.py";     DestDir: "{app}\app\payroll_app";         Flags: ignoreversion skipifsourcedoesntexist
Source: "files\payroll_app\import_loans.py";DestDir: "{app}\app\payroll_app";         Flags: ignoreversion skipifsourcedoesntexist

; ── Bundled Python runtime (no system Python required) ───────────────────────
Source: "python-embed.zip";      DestDir: "{app}";  Flags: ignoreversion
Source: "get-pip.py";            DestDir: "{app}";  Flags: ignoreversion

; ── WSGI entry point & helpers ────────────────────────────────────────────────
Source: "wsgi.py";               DestDir: "{app}";  Flags: ignoreversion
Source: "requirements.txt";      DestDir: "{app}";  Flags: ignoreversion
Source: "setup_env.bat";         DestDir: "{app}";  Flags: ignoreversion
Source: "launcher.vbs";          DestDir: "{app}";  Flags: ignoreversion
Source: "LICENSE.txt";           DestDir: "{app}";  Flags: ignoreversion
Source: "generate_manual.py";    DestDir: "{app}";  Flags: ignoreversion
Source: "SchoolMS_User_Manual.pdf"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\School Management System"; Filename: "wscript.exe"; Parameters: """{app}\launcher.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app\static\icons\logoRP.ico"; Comment: "Open School Management System in browser"
Name: "{group}\{cm:UninstallProgram,School Management System}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\School Management System"; Filename: "wscript.exe"; Parameters: """{app}\launcher.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\app\static\icons\logoRP.ico"; Comment: "Open School Management System in browser"; Tasks: desktopicon

[Run]
; Step 1 — Create virtual environment and install all Python dependencies
Filename: "{app}\setup_env.bat"; Parameters: "{app}"; StatusMsg: "Installing Python environment — this may take 2-3 minutes..."; Flags: runhidden waituntilterminated
; Step 2 — Open Windows Firewall port 5000 (optional task)
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""School Management System"" dir=in action=allow protocol=TCP localport=5000"; StatusMsg: "Configuring Windows Firewall for network access..."; Flags: runhidden waituntilterminated; Tasks: firewall
; Step 3 — Offer to launch immediately after install
Filename: "wscript.exe"; Parameters: """{app}\launcher.vbs"""; Description: "Launch School Management System now"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.python"
Type: filesandordirs; Name: "{app}\app\school.db"
Type: filesandordirs; Name: "{app}\app\payroll_app\payroll.db"
Type: filesandordirs; Name: "{app}\app\.env"
Type: files;          Name: "{app}\flask_*.txt"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    MsgBox(
      'School Management System v2.0 installed successfully!' + #13#10 + #13#10 +
      'What''s new in v2.0:' + #13#10 +
      '  - English / Spanish language switching' + #13#10 +
      '  - Role-based User Manual (PDF, opens in browser)' + #13#10 +
      '  - Auto-generated 10-digit Student & Staff IDs' + #13#10 +
      '  - Unified ID system across students, staff and payroll' + #13#10 + #13#10 +
      'First launch:' + #13#10 +
      '  1. You will be asked to enter your license key.' + #13#10 +
      '  2. Enter the key you received after purchase.' + #13#10 + #13#10 +
      'Default admin login:' + #13#10 +
      '  Username : admin' + #13#10 +
      '  Password : admin123' + #13#10 + #13#10 +
      'Change the password immediately after first login.' + #13#10 + #13#10 +
      'Support: ro1manramirez73@gmail.com',
      mbInformation, MB_OK);
  end;
end;
