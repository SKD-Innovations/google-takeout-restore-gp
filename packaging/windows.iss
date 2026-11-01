#define AppVersion "0.2.1"
[Setup]
AppId={{CB0D3D6A-5DE5-4412-899C-A28D5EF52EB7}
AppName=Takeout Restore
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Takeout Restore
DefaultGroupName=Takeout Restore
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installers
OutputBaseFilename=TakeoutRestore-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=icon.ico
LicenseFile=..\LICENSE
[Files]
Source: "..\dist\TakeoutRestore\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Takeout Restore"; Filename: "{app}\TakeoutRestore.exe"
Name: "{autodesktop}\Takeout Restore"; Filename: "{app}\TakeoutRestore.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Run]
Filename: "{app}\TakeoutRestore.exe"; Description: "Open Takeout Restore"; Flags: nowait postinstall skipifsilent
[Files]
Source: "..\vendor\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy
[Code]
function NeedsWebView2: Boolean;
var Version: String;
begin
  Result := not ((RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')));
end;
function PrepareToInstall(var NeedsRestart: Boolean): String;
var ResultCode: Integer;
begin
  Result := '';
  if NeedsWebView2 then begin
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
      Result := 'Microsoft WebView2 could not be installed. Check your internet connection and run Setup again.'
    else if NeedsWebView2 then
      Result := 'Microsoft WebView2 is required. Check your internet connection and run Setup again.';
  end;
end;
