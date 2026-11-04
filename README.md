# VoiceLab AI · v0.8.0

Estudio de voz para Windows 10/11: modulador en tiempo real con micrófono virtual, efectos, clonación de voz con IA local, conversión de voz en directo (RVC y voz instantánea sin entrenar), texto a voz, editor de audio y biblioteca de perfiles. Sin suscripciones: todo se ejecuta en tu equipo.

> Estado detallado de cada fase y de lo verificado: final de **ARQUITECTURA.md**.

## Instalar

**Para cualquier persona:** descarga `VoiceLabAI-Setup-<versión>.exe` desde la sección *Releases* del repositorio, ábrelo y sigue el asistente. Es un instalador normal de Windows: no necesita Python, ni permisos de administrador, ni consola. Crea los accesos directos y aparece en *Configuración → Aplicaciones* para desinstalarlo. Si Windows avisa («Windows protegió tu PC»), pulsa *Más información → Ejecutar de todas formas* (el instalador no está firmado con un certificado de pago).

El instalador lo genera GitHub Actions en Windows real (`.github/workflows/build.yml`): ejecuta las pruebas, compila con PyInstaller, comprueba el `.exe` (y que la ventana llega a abrirse), crea el instalador con Inno Setup, lo instala y lo desinstala en silencio, y prueba el texto a voz, RVC y la voz en directo con los modelos reales.

*Para desarrollo* sigue existiendo `Instalar VoiceLab AI.bat`, que instala desde el código con un Python privado.

**Micrófono virtual:** instala [VB-CABLE](https://vb-audio.com/Cable/) (gratis, firmado por Microsoft), reinicia y, opcionalmente, renombra «CABLE Output» a **VoiceLab AI Microphone** (*Ajustes → Abrir panel de Sonido*). En Discord, Steam o el navegador elige ese micrófono.

**IA (una sola vez):** *Ajustes → Motor de IA y modelos* → «Instalar ahora» (ONNX Runtime con DirectML para tu Radeon) y descarga los modelos que quieras:
- **Chatterbox Multilingual** (~3,2 GB, exportación ONNX oficial de onnx-community): texto a voz y clonación instantánea, 23 idiomas. Comprobado en Windows transcribiendo el resultado con Whisper (español: 97–100 % de coincidencia con el texto). La exportación comunitaria «V3» que usaban versiones anteriores no lee bien el texto: si la tienes, la app ofrece borrarla.
- **Base para conversión RVC** (~0,5 GB): necesaria para usar voces RVC en directo.
- **Voz instantánea en directo** (experimental, ~1,9 GB de descarga): hablar en tiempo real con una voz clonada de ~30 s, sin entrenar. Instala PyTorch para CPU en un entorno aparte. Ver más abajo.

## Qué puedes hacer

| Sección | Funciones |
|---|---|
| **Modulador** | Micrófono → efectos/IA → micrófono virtual, monitor (altavoces/auriculares) y salida auxiliar (p. ej. teléfono). Medidores, latencia, puerta de ruido, limitador, escuchar tu voz original, Ctrl+M |
| **Efectos** | Tono, formantes, robot, reducción de ruido, pasaaltos/pasabajos, graves/medios/agudos, EQ de 10 bandas, compresor, limitador, saturación, distorsión, lo-fi, modulación en anillo, chorus, eco, reverberación. 11 preajustes |
| **Clonar voz** | Arrastra audio o vídeo, elige el fragmento, limpieza, análisis (voz útil, ruido, tono, suficiencia), confirmación de autorización → perfil de IA instantánea |
| **Crear voz** | Estudio de grabación con textos para leer; usa tus tomas para clonar o edítalas |
| **Texto a voz** | Cualquier texto (también largo) con tus voces clonadas; velocidad, estabilidad, expresividad, idioma; WAV/MP3/FLAC/OGG |
| **Editor** | Forma de onda, recortar, eliminar, silenciar, dividir, unir, fundidos, volumen, normalizar, quitar silencios, reducir ruido, efectos, tempo y velocidad, deshacer, exportar |
| **Biblioteca** | Perfiles con nombre, imagen, descripción, carpeta, favoritos, búsqueda; duplicar, exportar/importar (`.vlprofile`), copias de seguridad; importar modelos **RVC (.onnx)** para la voz en directo |

## Voz instantánea en directo (experimental)

Para hablar en directo con una voz de la que solo tienes ~30 s (un perfil creado en *Clonar voz*), sin entrenar nada:

1. *Ajustes → Motor de IA → Voz instantánea en directo → Instalar*. Descarga PyTorch 2.5.1 para CPU (PyPI) en `vc-runtime\` dentro de la carpeta de la app, los modelos de **MeanVC2** (ASLP-lab, Apache 2.0, Hugging Face) y el codificador de hablante WavLM-Large/ECAPA de Microsoft UniSpeech (1,3 GB, réplica en Hugging Face verificada con SHA-256). Al terminar mide la velocidad en tu CPU.
2. En el **Modulador**, elige el perfil de IA instantánea: aparece «Hablar en directo con esta voz». La primera vez con cada voz calcula su huella (unos segundos) y la guarda en el perfil.

Cómo funciona: un proceso aparte (PyTorch no entra en la app ni compite con el audio) recibe bloques de 160 ms a 16 kHz y devuelve la voz convertida. Modos *Calidad* (120 ms) y *Baja latencia* (40 ms). Latencia total orientativa: 300–450 ms.

Límites honestos: es conversión *zero-shot*, se parece menos que un modelo RVC entrenado con esa voz; el modelo se entrenó sobre todo con inglés y chino, así que en español la pronunciación puede sonar menos natural; solo usa la CPU. No se ha podido probar con los modelos reales en el entorno de desarrollo (sin acceso a Hugging Face/PyPI); la lógica alrededor está probada con un proceso simulado. Úsalo solo con voces propias o con autorización.

### Calidad de la voz de IA en directo (v0.8)

- **Limpiar mi voz antes de convertir** (por defecto): paso alto y reducción de ruido suave antes del modelo.
- **Acabado de estudio** (por defecto): control de eses, compresión suave, presencia y volumen constante a la salida, como en una voz producida.
- **Alta definición 48 kHz** (voz instantánea): MeanVC2 sale a 16 kHz; [AP-BWE](https://github.com/yxlu-0102/AP-BWE) (MIT) reconstruye los agudos hasta 48 kHz. Descarga de 120 MB desde el Google Drive del autor, con SHA-256. Se mide al instalar y solo se usa si la CPU lo aguanta. Comprobado en Windows: la voz se sigue entendiendo igual (Whisper 99 %).

Límite honesto: los servicios como ElevenLabs usan modelos enormes en servidores; en directo y con la CPU de casa no se puede igualar del todo. Estas mejoras acercan el resultado en nitidez y acabado.

## Voces RVC en directo

La conversión en tiempo real necesita un modelo RVC entrenado con 10–30 min de voz. VoiceLab guarda ese material (`material.wav` del perfil) cuando clonas con suficiente audio. El entrenamiento se hace fuera de la app (por ejemplo con Applio), exportando a **ONNX**; después usa *Biblioteca → Importar modelo RVC*. VoiceLab detecta el formato y la frecuencia del modelo y lo usa en el modulador con DirectML.

## Compilar el instalador .exe (Fase 7)

- **En tu PC:** instala Python 3.12 e [Inno Setup 6](https://jrsoftware.org/isinfo.php) y ejecuta `build\build_exe.bat` → `dist\VoiceLabAI-Setup-<versión>.exe` (incluye el motor de IA).
- **Sin instalar nada:** sube la carpeta a un repositorio de GitHub; el flujo `.github/workflows/build.yml` compila el instalador y lo deja como artefacto descargable.

## Si algo falla

| Problema | Solución |
|---|---|
| Chasquidos | *Ajustes → Rendimiento*: margen anticortes 3 o bloque 512 |
| Cortes con voz RVC | Sube el tamaño de bloque RVC o usa una voz con modelo más ligero; mira «inferencia» en el modulador |
| Voz instantánea: cortes o «la CPU no da abasto» | Usa el modo *Calidad* (menos cálculo que *Baja latencia*) y cierra programas pesados; registro en `%APPDATA%\VoiceLabAI\logs\voz-instantanea.log` |
| Voz instantánea: error con una DLL | Instala el [Microsoft Visual C++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe) |
| «Windows no ha permitido abrir…» | Otra app usa el dispositivo en modo exclusivo (panel de Sonido → Propiedades → Opciones avanzadas) |
| El texto a voz va lento | La primera generación carga el modelo (hasta ~1 min); después se queda cargado. Se puede probar la GPU en *Ajustes → Motor de IA*; si falla, la app vuelve sola a la CPU |
| El instalador .bat falla | Pega el contenido de `%TEMP%\voicelab-install.log` |
| La app falla | Registros en `%APPDATA%\VoiceLabAI\logs\`: `voicelab.log`, `texto-a-voz.log`, `rvc.log`, `voz-instantanea.log` y `fallos.log` (cierres inesperados) |

## Desarrollo

`python -m voicelab --browser` (modo navegador) · `python -m pytest` (131 pruebas) · `python tools/ui_check*.py` (pruebas de interfaz con Playwright).
