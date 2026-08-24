#define MyAppName "Dubora"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Hamza Omar"
#define MyAppExeName "Dubora.exe"

[Setup]
AppId={{D4E8F205-1C25-4C65-A6EC-65A6CF5B2A91}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Dubora
DefaultGroupName=Dubora
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=Dubora-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes
SetupIconFile=assets\dubora.ico

[Files]
Source: "dist\Dubora\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Dubora"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Dubora"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Dubora"; Flags: nowait postinstall skipifsilent
