#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId=PickLight.YangMu
AppName=PickLight
AppVersion={#AppVersion}
AppPublisher=Yang Mu
DefaultDirName={localappdata}\Programs\PickLight
DefaultGroupName=PickLight
DisableProgramGroupPage=yes
OutputDir=..\dist\Release
OutputBaseFilename=PickLight-{#AppVersion}-Setup
SetupIconFile=..\assets\picklight.ico
UninstallDisplayIcon={app}\PickLight.exe
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\dist\Preview\PickLight\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\PickLight"; Filename: "{app}\PickLight.exe"
Name: "{autodesktop}\PickLight"; Filename: "{app}\PickLight.exe"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"
