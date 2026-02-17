#define AppName "TradingBot"
#define AppVersion "1.0.0"
#define AppPublisher "TradingBot"
#define ExeName "TradingBot.exe"

[Setup]
AppId={{3E3A0A5B-3A6D-448D-A2BF-61B72A18A3C8}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\TradingBot
DefaultGroupName={#AppName}
OutputDir=dist
OutputBaseFilename=TradingBotSetup
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
Source: "..\..\dist\TradingBot\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs

[Icons]
Name: "{group}\TradingBot"; Filename: "{app}\{#ExeName}"
Name: "{autodesktop}\TradingBot"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExeName}"; Description: "Executar TradingBot"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Mantém dados do usuário em %LOCALAPPDATA%\TradingBot por padrão.
