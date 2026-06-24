; Inno Setup script для Суфлёр (Windows).
; Собирает установщик из папки dist\Sufler (вывод PyInstaller).
;
; Локально:  iscc packaging\windows\installer.iss
; Версию можно передать:  iscc /DMyAppVersion=2.1.0 packaging\windows\installer.iss

#ifndef MyAppVersion
  #define MyAppVersion "2.0.0"
#endif

#define MyAppName "Суфлёр"
#define MyAppExeName "Sufler.exe"
#define MyAppPublisher "Sufler"

[Setup]
AppId={{B6A9E3C2-7F1D-4E55-9C3A-SUFLER000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Sufler
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=Sufler-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Запускать при входе в систему"; GroupDescription: "Автозапуск:"; Flags: unchecked

[Files]
; Вся папка сборки PyInstaller (dist\Sufler\*)
Source: "..\..\dist\Sufler\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
