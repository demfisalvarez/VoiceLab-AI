; Inno Setup 6: instalador de VoiceLab AI (por usuario, sin permisos de administrador)
#define AppVersion GetEnv("VL_VERSION")
[Setup]
AppId={{6B7C0E0A-6F6F-4F7B-9B0E-56D1A1A0C0DE}
AppName=VoiceLab AI
AppVersion={#AppVersion}
AppVerName=VoiceLab AI {#AppVersion}
AppPublisher=VoiceLab AI
DefaultDirName={localappdata}\Programs\VoiceLab AI
DefaultGroupName=VoiceLab AI
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=VoiceLabAI-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\VoiceLab AI.exe
UninstallDisplayName=VoiceLab AI
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Si la app está abierta, el instalador pide cerrarla (mismo nombre que su mutex de instancia única).
AppMutex=VoiceLabAI_SingleInstance
CloseApplications=yes

ShowLanguageDialog=auto
LanguageDetectionMethod=uilanguage

[Languages]
; El asistente sale en el idioma de Windows (si no está, en inglés).
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"
; El chino simplificado es una traducción «no oficial» de Inno Setup: el flujo de CI la descarga
; de github.com/jrsoftware/issrc; si no está, el instalador sale sin chino (en inglés).
#if FileExists(AddBackslash(SourcePath) + "ChineseSimplified.isl")
Name: "zh"; MessagesFile: "ChineseSimplified.isl"
#endif

[CustomMessages]
en.OpenCable=Open the VB-CABLE page (free virtual microphone)
es.OpenCable=Abrir la página de VB-CABLE (micrófono virtual gratuito)
fr.OpenCable=Ouvrir la page de VB-CABLE (micro virtuel gratuit)
it.OpenCable=Apri la pagina di VB-CABLE (microfono virtuale gratuito)
pt.OpenCable=Abrir a página do VB-CABLE (microfone virtual gratuito)
ru.OpenCable=Открыть страницу VB-CABLE (бесплатный виртуальный микрофон)
ja.OpenCable=VB-CABLE のページを開く（無料の仮想マイク）
#if FileExists(AddBackslash(SourcePath) + "ChineseSimplified.isl")
zh.OpenCable=打开 VB-CABLE 页面（免费的虚拟麦克风）
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Restos de la instalación antigua con «Instalar VoiceLab AI.bat» (Python a la vista): se sustituyen por el .exe.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\voicelab"
Type: filesandordirs; Name: "{app}\installer"
Type: filesandordirs; Name: "{app}\assets"
Type: files; Name: "{app}\requirements.txt"
Type: files; Name: "{app}\README.md"
Type: files; Name: "{app}\ARQUITECTURA.md"
Type: filesandordirs; Name: "{app}\vc-python"
Type: files; Name: "{userprograms}\VoiceLab AI.lnk"
Type: files; Name: "{userdesktop}\VoiceLab AI.lnk"

[Registry]
; Entrada de «Aplicaciones» de la instalación antigua (la nueva la crea este instalador).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceLabAI"; ValueType: none; Flags: deletekey

[Files]
Source: "..\dist\VoiceLab AI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\VoiceLab AI"; Filename: "{app}\VoiceLab AI.exe"; AppUserModelID: "VoiceLabAI.Studio"
Name: "{userdesktop}\VoiceLab AI"; Filename: "{app}\VoiceLab AI.exe"; AppUserModelID: "VoiceLabAI.Studio"; Tasks: desktopicon

[Run]
Filename: "https://vb-audio.com/Cable/"; Description: "{cm:OpenCable}"; Flags: postinstall shellexec skipifsilent unchecked
Filename: "{app}\VoiceLab AI.exe"; Description: "{cm:LaunchProgram,VoiceLab AI}"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Componentes que la app descarga después (voz en directo): se borran al desinstalar.
Type: filesandordirs; Name: "{app}\vc-runtime"
Type: filesandordirs; Name: "{app}\vc-python"
