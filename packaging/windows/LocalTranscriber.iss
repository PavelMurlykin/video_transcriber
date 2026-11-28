#ifndef Version
  #error Version is required
#endif
#ifndef Bundle
  #error Bundle is required
#endif
#ifndef Icon
  #error Icon is required
#endif

[Setup]
AppId=LocalTranscriber.Windows
AppName=Local Transcriber
AppVersion={#Version}
DefaultDirName={localappdata}\Programs\Local Transcriber
DefaultGroupName=Local Transcriber
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
SetupIconFile={#Icon}
UninstallDisplayIcon={app}\LocalTranscriber.exe
OutputBaseFilename=LocalTranscriber-{#Version}-windows-x64
Compression=lzma2/fast
SolidCompression=yes
DiskSpanning=yes
DiskSliceSize=max
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "{#Bundle}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Local Transcriber"; Filename: "{app}\LocalTranscriber.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Local Transcriber"; Filename: "{app}\LocalTranscriber.exe"; WorkingDir: "{app}"; Tasks: desktopicon
