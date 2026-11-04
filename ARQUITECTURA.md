# VoiceLab AI — Análisis técnico y arquitectura

Documento de decisiones previo al desarrollo. Revisado en noviembre de 2026 para tu equipo:
**Ryzen 7 5700X · 32 GB DDR4 · Radeon RX 6600 8 GB · Windows 11**.

---

## 1. Resumen: qué es viable y qué no

| Requisito | ¿Viable? | Cómo |
|---|---|---|
| Interfaz de escritorio moderna | Sí | Ventana nativa WebView2 (Edge) con interfaz HTML/CSS y motor en Python |
| Micrófono virtual para todo Windows | Sí, con un driver externo | VB-CABLE (driver firmado por Microsoft), renombrado a **VoiceLab AI Microphone** |
| Driver de micrófono propio con nombre propio | No para un proyecto personal | Exige firma de drivers de kernel con certificado EV y atestación de Microsoft (de pago, anual) |
| Modulación tradicional en tiempo real | Sí | DSP propio (NumPy/SciPy) sobre WASAPI, ~30–50 ms de latencia total |
| Clonación "instantánea" (segundos de audio) | Sí | Chatterbox Multilingual V3 (MIT, incluye español de España) en ONNX + DirectML |
| Conversión voz→voz por IA en tiempo real | Sí, con un modelo entrenado | RVC v2 exportado a ONNX y ejecutado con DirectML en la RX 6600 |
| Entrenar modelos RVC en la RX 6600 bajo Windows | Limitado | Sin PyTorch oficial para RDNA2 en Windows: CPU (lento), ROCm no oficial o Linux |
| Conversión en tiempo real *sin entrenar* (zero-shot) | Experimental | Seed-VC: ~430 ms de latencia incluso en GPU NVIDIA; en AMD/Windows, dudoso |
| Texto a voz con voces clonadas | Sí | Chatterbox Multilingual V3 (23 idiomas, clonación con ~10 s) |
| Funcionamiento sin conexión y sin cuotas | Sí | Todos los modelos elegidos son locales y de licencia permisiva |

**Conclusión:** el proyecto es realizable con calidad real en tu equipo, con dos matices honestos:
1. El micrófono virtual lo pone un driver externo gratuito (VB-CABLE); VoiceLab AI lo controla y lo renombra.
2. La mejor conversión en tiempo real (RVC) necesita **entrenar un modelo por voz** con 10–30 min de audio limpio. La parte de *usarlo* en tiempo real funciona en tu RX 6600; la de *entrenarlo* es el cuello de botella en Windows con AMD.

---

## 2. Qué implica tu hardware

- **RX 6600 (RDNA2, gfx1032):**
  - **DirectML: sí.** Funciona en cualquier GPU DirectX 12. ONNX Runtime + DirectML es la vía probada para RVC en AMD (el voice changer de w-okada y RVC distribuyen variantes DirectML y un `rmvpe.onnx` específico para AMD/Intel).
  - **ROCm / PyTorch oficial en Windows: no.** Las ruedas oficiales de AMD para Windows solo cubren RDNA3 (RX 7000) y RDNA4 (RX 9000). Para RDNA2 existen compilaciones nocturnas no oficiales (TheRock, ROCm 7.12+) que *pueden* funcionar, pero no son una base estable para distribuir.
  - DirectML está en "mantenimiento" (sustained engineering): sigue soportado y funciona, pero Microsoft desarrolla lo nuevo en **Windows ML**, que expone la misma API de ONNX Runtime. Diseñaremos la capa de IA sobre ONNX Runtime para poder cambiar DirectML ↔ Windows ML ↔ CPU sin tocar el resto.
- **8 GB de VRAM:** suficiente para Chatterbox (~0,5 B parámetros) y para RVC + extractor de tono a la vez, no para modelos grandes simultáneos. La app cargará un modelo de IA cada vez.
- **Ryzen 7 5700X (8 núcleos / 16 hilos):** el motor de audio, el DSP, la reducción de ruido (DeepFilterNet3 en CPU va ~7× más rápido que tiempo real) y el respaldo sin GPU van en CPU. RVC en CPU es posible pero con más latencia.
- **32 GB de RAM:** sin problemas para editar archivos largos y procesar en segundo plano.

---

## 3. Pila tecnológica elegida

| Capa | Tecnología | Licencia | Motivo |
|---|---|---|---|
| Lenguaje del motor | Python 3.12 | PSF | Todos los modelos de voz (RVC, Chatterbox, Seed-VC, DeepFilterNet) tienen su pre/postproceso en Python |
| Ventana | pywebview → WebView2 (Edge Chromium) | BSD-3 | Ventana nativa de Windows con interfaz web moderna; WebView2 viene con Windows 10/11 |
| Interfaz | HTML + CSS + JavaScript sin frameworks | propia | Ligera, sin compilación, animaciones fluidas |
| Audio | sounddevice → PortAudio → **WASAPI** | MIT | Acceso directo a WASAPI con baja latencia; elige cualquier dispositivo de Windows |
| DSP | NumPy / SciPy | BSD | Efectos tradicionales propios, sin dependencias GPL |
| Inferencia IA | ONNX Runtime + DirectML (respaldo CPU) | MIT | Compatible con AMD, sin CUDA |
| Reducción de ruido | DeepFilterNet3 (ONNX) | MIT / Apache-2.0 | Tiempo real en CPU, ~32 ms de latencia algorítmica |
| Vídeo → audio | FFmpeg (compilación LGPL) | LGPL | Extraer pistas de MP4/MKV/MOV/WEBM |
| Micrófono virtual | VB-CABLE (driver firmado) | Donationware | Estable, firmado por Microsoft, aparece como dispositivo estándar |
| Instalador | Fase 1: script PowerShell + uv (Python privado) · Fase 7: PyInstaller + Inno Setup | MIT/Apache · GPL con excepción / modificada BSD | No depende del Python del usuario; ejecutable, acceso directo y desinstalador |

**Por qué no Qt/Electron/C++:** Qt obligaría a reescribir todos los widgets y no aporta frente a WebView2; Electron añade ~150 MB y otro runtime; C++/JUCE sería ideal para audio pero haría inviable integrar los modelos de voz, que solo existen en Python/ONNX.

---

## 4. Micrófono virtual de Windows

### Opciones evaluadas

1. **Driver propio "VoiceLab AI Microphone".** Un driver de audio es código de kernel; Windows 11 solo lo carga si está firmado por Microsoft mediante atestación, lo que requiere un certificado EV de empresa (de pago, anual). Descartado para un proyecto personal.
2. **VB-CABLE (VB-Audio). ELEGIDO.** Driver firmado, gratuito (donationware), maduro y usado por Voicemeeter, OBS y muchos voice changers. Crea una pareja de dispositivos:
   - `CABLE Input` → **salida** donde VoiceLab AI escribe la voz procesada.
   - `CABLE Output` → **micrófono** que eligen Discord, Steam, juegos o el navegador.
3. **Virtual-Audio-Driver (VirtualDrivers).** Código abierto (MIT), firmado vía SignPath, con altavoz y micrófono virtuales. Sigue en beta y se instala a mano desde el Administrador de dispositivos. Alternativa futura si madura.
4. **Voicemeeter.** Funciona, pero es un mezclador completo: demasiada complejidad para este uso.

### Cómo queda para el usuario

```
Micrófono físico (Realtek) ─► VoiceLab AI (procesado) ─► CABLE Input ══► CABLE Output
                                                                         renombrado a
                                                               "VoiceLab AI Microphone"
                                                                          │
                                         Discord · Steam · juegos · navegador · Zoom
```

- El renombrado se hace **una vez** en *Panel de Sonido → Grabación → CABLE Output → Propiedades*. Windows lo muestra después como **VoiceLab AI Microphone** en todas las aplicaciones. La app abre ese panel y detecta el nombre.
- La licencia de VB-CABLE permite distribuirlo junto con otro producto siempre que el usuario lo identifique como de VB-Audio y pueda donar. Para uso personal, el instalador **no lo empaqueta**: guía a la descarga oficial.

---

## 5. Clonación y conversión de voz por IA

Hay dos familias de tecnología y la app las usará para cosas distintas.

### 5.1 Clonación instantánea (zero-shot): segundos de audio, sin entrenar

| Modelo | Uso | Audio necesario | AMD/Windows | Licencia |
|---|---|---|---|---|
| **Chatterbox Multilingual V3** (Resemble AI) | Texto a voz con voz clonada, 23 idiomas, ajuste fino específico de español de España | ~10 s | Exportaciones ONNX, incluida una adaptada a DirectML | MIT (el paquete oficial de Python añade la marca de agua PerTh; la vía ONNX que usa VoiceLab no la añade) |
| XTTS-v2 (Coqui) | Texto a voz | ~6 s | PyTorch; CPU viable | CPML: **solo uso no comercial** |
| F5-TTS | Texto a voz | ~10 s | PyTorch | Código MIT, pesos no comerciales |
| Seed-VC | Voz→voz sin entrenar, también en tiempo real | 1–30 s | Solo PyTorch; en tiempo real exige GPU potente | No declarada con claridad en el README (se revisará) |

**Decisión:** Chatterbox Multilingual V3 como motor principal de **texto a voz** y de **perfil instantáneo**. Seed-VC queda como opción **experimental** para conversión de archivos sin entrenar.

### 5.2 Modelo entrenado (RVC v2): la mejor calidad en tiempo real

- **RVC (Retrieval-based Voice Conversion) v2**, licencia MIT. Es el estándar de facto de los voice changers por IA: conserva timbre, resonancia y forma de hablar, y el usuario mantiene su entonación y sus palabras.
- **Datos necesarios:** 10–30 min de voz limpia (sin música, ruido ni eco). Con menos de 5 min suele dar malos resultados. La app medirá la duración útil y mostrará un indicador de suficiencia.
- **Inferencia en la RX 6600:** modelo exportado a ONNX + extractor de tono RMVPE en ONNX, ejecutados con DirectML. Es la ruta que ya usan los voice changers de la comunidad en tarjetas AMD.
- **Entrenamiento (el punto débil):**
  1. **CPU (5700X):** funciona sin instalar nada raro; un modelo decente puede llevar una noche entera.
  2. **ROCm no oficial para RDNA2 en Windows:** posible y mucho más rápido, pero experimental. Se ofrecerá como opción avanzada con advertencia.
  3. **Linux con ROCm** (arranque dual): la vía más rápida y estable con AMD.
  4. **Importar modelos RVC ya entrenados** (`.pth`/`.onnx`) de voces propias o autorizadas.
  5. Entrenamiento en la nube (p. ej. Colab): **no por defecto**. Si se añade, se avisará antes de usarlo, como pides.
- **Alternativa de latencia ultrabaja: Beatrice v2.** Corre en un solo hilo de CPU con menos de 50 ms, pero su entrenamiento requiere GPU NVIDIA y su motor tiene licencia propia. Queda como opción a estudiar en la Fase 4.

### 5.2 bis Voz instantánea en directo (MeanVC2, experimental, v0.6)

Para hablar en directo con una voz de la que solo hay ~30 s, sin entrenar:

- **Modelo:** [MeanVC2](https://github.com/ASLP-lab/MeanVC2) (ASLP-lab, 2026, Apache 2.0, ~18 M parámetros). Conversión *zero-shot* en streaming: codificador ASR Fast-U2++ (contenido), huella de hablante WavLM-Large + ECAPA-TDNN (UniSpeech, Microsoft), decodificador DiT con «mean flows» y vocoder Vocos a 16 kHz. Modos 120 ms y 40 ms de bloque.
- **Por qué PyTorch y no ONNX:** los modelos se publican en TorchScript/safetensors con cachés de streaming; exportarlos a ONNX sin poder probarlos sería arriesgado. Se usa **PyTorch 2.5.1 para CPU** (la versión que fija el proyecto) en un entorno aparte, `vc-runtime\`, dentro de la carpeta de la app; se instala a petición con el mismo `uv` del instalador.
- **Proceso aparte** (`voicelab/ai/meanvc_worker.py`): la app nunca importa PyTorch. Protocolo binario por tuberías (tipo + longitud + datos). El motor de audio solo copia muestras; un hilo remuestrea 48/44,1 kHz ↔ 16 kHz con un **remuestreador polifásico en streaming** (`audio/resampler.py`, idéntico troceado o entero), envía bloques exactos de 2560 muestras (160 ms) y devuelve el resultado con un colchón que se recompone si se vacía (silencio, nunca la voz original).
- **Huella de voz:** se calcula una vez por perfil a partir de `reference.wav` (hasta 30 s) y se guarda en `meanvc_voice.json`; el modelo de hablante (1,3 GB) solo se carga para eso. Cambiar entre voces instantáneas reutiliza el proceso.
- **Configuración de WavLM-Large:** se incluye en el código (igual que `config.json` de microsoft/wavlm-large) para no descargar 1,26 GB solo por ella; al cargar los pesos se comprueba que no falte ninguno.
- **Código de terceros:** `voicelab/ai/vendor/meanvc2/` contiene `runtime/` y `src/config/` de MeanVC2 sin modificar y un subconjunto mínimo de s3prl (Apache 2.0; WavLM con licencia MIT de Microsoft). Ver `NOTICE.md`.
- **Pesos:** `ASLP-lab/MeanVC2` en Hugging Face; el codificador de hablante, publicado por Microsoft en Google Drive, se baja de una réplica en Hugging Face (`Dongchao/UniAudio` y dos alternativas) con SHA-256.
- **Límites:** menos parecido que RVC entrenado; entrenado sobre todo con inglés y chino (datos Emilia), así que el español puede sonar menos natural; solo CPU (RTF < 0,63 en un núcleo según los autores). Latencia total orientativa 300–450 ms.

### 5.3 Flujo de "Clonar voz" (Fase 3)

1. Arrastrar audio o vídeo → extracción de audio con FFmpeg.
2. Selección de fragmento sobre la forma de onda.
3. Limpieza: separación voz/fondo (modelo MDX/UVR en ONNX) y reducción de ruido (DeepFilterNet3).
4. Análisis: duración útil de voz, relación señal/ruido, tono medio y rango, saturación.
5. Indicador de suficiencia: **< 10 s** insuficiente · **10–30 s** perfil instantáneo (TTS) · **5–10 min** RVC básico · **10–30 min** RVC de calidad.
6. Confirmación de autorización cuando la voz no es tuya (requisito de tu especificación).
7. Creación del perfil: instantáneo (Chatterbox) y/o entrenamiento RVC en segundo plano con barra de progreso.
8. Prueba de escucha → guardar en la biblioteca.

> La app nunca llamará "voz clonada" a un perfil que solo cambie el tono: los perfiles tendrán un tipo visible (**Efectos** / **IA instantánea** / **IA entrenada (RVC)**).

---

## 6. Procesamiento tradicional (Fase 2)

Cadena DSP propia en NumPy/SciPy, en tiempo real y combinable:

- Pitch y formantes: *phase vocoder* con corrección de formantes (envolvente espectral) para voz grave/aguda natural.
- Tempo sin alterar el tono y velocidad (en archivos y TTS).
- Ecualizador gráfico de 10 bandas, graves/medios/agudos (biquads), pasaaltos y pasabajos.
- Compresor, limitador, puerta de ruido, ganancia.
- Reverberación (Schroeder/Freeverb), eco, chorus, distorsión y saturación.
- Reducción de ruido IA: DeepFilterNet3 ONNX en CPU.
- Cancelación de eco: WebRTC AEC3 o SpeexDSP, solo necesaria si se monitoriza por altavoces.
- Preajustes: muy grave, grave, aguda, infantil ficticia, robótica, monstruo, radio, teléfono, megáfono, extraterrestre y videojuego.

---

## 7. Arquitectura interna

```
┌──────────────── Ventana WebView2 (interfaz HTML/CSS/JS) ────────────────┐
│ Inicio · Modulador · Biblioteca · Clonar · Crear · TTS · Editor · Ajustes│
└──────────────▲───────────────────────────────────────────────────────────┘
               │ llamadas asíncronas (pywebview js_api), sondeo de medidores a 20 Hz
┌──────────────┴──────────── voicelab.api (Python) ────────────────────────┐
│ Ajustes · Dispositivos · Perfiles · Tareas largas (hilos/procesos)        │
└──────┬───────────────────────────────────────────────┬───────────────────┘
       │                                               │
┌──────▼────────── Motor de audio en tiempo real ──────┐   ┌──────────────────────┐
│ Hilo PortAudio entrada (WASAPI)                      │   │ Trabajador de IA       │
│  mic → ganancia → puerta → [cadena DSP / IA] → medir │◄─►│ (proceso aparte desde  │
│        │ escribe en búferes circulares por salida    │   │  la Fase 4: ONNX+DML)  │
│ Hilos PortAudio salida (uno por destino):            │   └──────────────────────┘
│  • Micrófono virtual (CABLE Input)                   │
│  • Monitorización (altavoces/auriculares)            │
│  • Salida auxiliar (p. ej. adaptador para teléfono)  │
│  volumen → limitador de seguridad → dispositivo      │
└──────────────────────────────────────────────────────┘
```

Principios:
- **La interfaz nunca bloquea el audio.** El audio vive en hilos de PortAudio; la interfaz solo lee medidores y envía parámetros.
- **Un búfer circular por destino.** Cada dispositivo tiene su propio reloj; el búfer absorbe la deriva y descarta o rellena de forma controlada para que la latencia no crezca.
- **Limitador de seguridad** en todas las salidas para evitar picos y acoples peligrosos.
- **La IA en tiempo real irá en un proceso separado** (Fase 4) para que la inferencia no compita con el audio por el GIL de Python.
- **Todo local:** ajustes, perfiles y modelos en `%APPDATA%\VoiceLabAI`.

---

## 8. Latencias esperadas

| Modo | Latencia total estimada |
|---|---|
| Voz original / efectos tradicionales (WASAPI compartido, búfer 256) | 30–50 ms |
| + reducción de ruido DeepFilterNet3 | +30–40 ms |
| Conversión RVC en RX 6600 (DirectML) | 200–350 ms (a medir en la Fase 4) |
| Conversión RVC solo CPU | 350–600 ms |
| Seed-VC zero-shot | ~430 ms o más, incluso en GPU NVIDIA |
| Voz instantánea en directo (MeanVC2, CPU) | 300–450 ms (bloque de 160 ms + cálculo + colchón; a medir en tu PC) |

Por debajo de ~150 ms la conversión por IA no es realista en ninguna herramienta actual con tarjetas de gama media. Los efectos tradicionales sí son prácticamente instantáneos.

---

## 9. Licencias

| Componente | Licencia | Uso en VoiceLab AI |
|---|---|---|
| Python, NumPy, SciPy | PSF / BSD | Incluido |
| sounddevice / PortAudio | MIT | Incluido |
| pywebview / bottle / proxy_tools | BSD / MIT | Incluido |
| pythonnet | MIT | Incluido (lo usa pywebview en Windows) |
| WebView2 Runtime | Microsoft (redistribuible) | Viene con Windows |
| ONNX Runtime (DirectML) | MIT | Fase 3 |
| Chatterbox Multilingual V3 | MIT | Fase 3/5 (descarga única del modelo) |
| RVC v2 | MIT | Fases 3/4 |
| MeanVC2 (código y pesos) | Apache 2.0 | Voz instantánea en directo (descarga a petición) |
| s3prl (subconjunto) / WavLM / ECAPA (UniSpeech) | Apache 2.0 / MIT | Codificador de hablante de MeanVC2 |
| PyTorch 2.5.1 (CPU) | BSD | Entorno aparte `vc-runtime`, solo si se instala la voz instantánea en directo |
| DeepFilterNet3 | MIT / Apache-2.0 | Fase 2 |
| FFmpeg | LGPL (compilación sin componentes GPL) | Fase 3 |
| VB-CABLE | Donationware, no se redistribuye | Instalación guiada |
| XTTS-v2 / F5-TTS | No comerciales | Opcionales, solo uso personal, con aviso |

No hay ninguna API de pago ni servicio externo obligatorio. Si en el futuro se añade alguno (p. ej. entrenamiento en la nube), la app lo indicará claramente antes de usarlo.

---

## 10. Plan por fases y criterio de "fase terminada"

| Fase | Contenido | Se da por terminada cuando… |
|---|---|---|
| **1** | Interfaz, ajustes, sistema de dispositivos, motor de audio en tiempo real (ganancia, puerta de ruido, medidores, latencia, rutas a micrófono virtual / monitor / auxiliar, limitador), instalador básico | El motor pasa pruebas con audio real y reloj simulado; la interfaz funciona de punta a punta |
| 2 | Cadena DSP completa, preajustes, perfiles de efectos, "escuchar original", reducción de ruido IA, cancelación de eco, renombrado asistido del cable | Cada efecto tiene prueba numérica; latencia medida < 60 ms |
| 3 | Importación audio/vídeo, recorte, limpieza, análisis, perfiles IA (Chatterbox) y entrenamiento/importación RVC | Un perfil se crea, se escucha y se guarda |
| 4 | Conversión IA en tiempo real (RVC ONNX + DirectML) en proceso aparte | Latencia medida y estable 10 min sin cortes |
| 5 | Texto a voz con historial y exportación WAV/MP3/FLAC/OGG | Textos largos por fragmentos sin bloquear |
| 6 | Editor de audio y biblioteca completa (carpetas, favoritos, importar/exportar, copias) | Archivos de 1 h editables sin congelar la interfaz |
| 7 | Optimización, pruebas, ejecutable e instalador `.exe` | Instalación limpia en Windows 11 sin consola |

---

## 11. Riesgos y limitaciones

- **Sin pruebas en tu Windows real todavía:** el motor se ha verificado con PortAudio real sobre ALSA en Linux y con un simulador de dispositivos de tiempo real. Las particularidades de WASAPI con tu Realtek y VB-CABLE se validarán en tu equipo al cerrar la Fase 1.
- **Deriva de reloj entre dispositivos:** en la Fase 1 se corrige descartando o rellenando bloques (un clic imperceptible cada pocos minutos como máximo). En la Fase 7 se sustituirá por remuestreo adaptativo.
- **Python y tiempo real:** con búferes de 256 muestras y la IA en otro proceso es estable. Si hiciera falta, el motor puede pasarse a un proceso dedicado sin cambiar la interfaz.
- **Entrenamiento RVC en AMD/Windows:** lento en CPU; la vía rápida depende de ROCm no oficial o de Linux.
- **Uso responsable:** la clonación de voces de terceros requiere su autorización. La app exige esa confirmación al crear cada perfil.

---

## 11 bis. Cambios de la v0.7.0 (a partir de los registros del PC del usuario)

- **Arranque:** la interfaz se rendía a los 4 s si el puente de pywebview no estaba listo (arranque en frío), y había que abrir la app dos veces. Ahora espera hasta 2 min sondeando el puente y ofrece «Reintentar».
- **Texto a voz que congelaba la app:** crear una sesión de ONNX Runtime no suelta el GIL de Python; cargar los 1,5 GB de Chatterbox bloqueaba la ventana durante mucho tiempo (y un fallo de DirectML podía cerrar la app). Todos los modelos ONNX (texto a voz y RVC) se cargan ahora en **procesos aparte** (`ai/procs.py`, multiprocessing «spawn»), con avisos de etapa, cancelación, vigilante de cuelgues y vuelta automática a la CPU si la GPU falla. El texto a voz usa la CPU por defecto.
- **Distribución:** instalador normal (`VoiceLabAI-Setup.exe`, PyInstaller + Inno Setup) compilado y probado en Windows por GitHub Actions. El `.exe` incluye `uv` para poder instalar la voz en directo (descarga un Python oficial y PyTorch aparte).
- **Diagnóstico:** `logs/fallos.log` (faulthandler), registros por proceso de IA, tiempos de carga y de cada tarea, y `--selftest` / `--selftest-window` para la compilación.

## 12. Estado de implementación (v0.7.0)

| Fase | Estado | Verificación |
|---|---|---|
| 1 · Interfaz y dispositivos | Hecha | Pruebas con PortAudio real y simulador de Windows; interfaz en Chromium |
| 2 · Efectos y micrófono virtual | Hecha | Prueba numérica de cada efecto, 11 preajustes, perfiles, escucha del original |
| 3 · Clonación | Hecha (importar audio/vídeo, recorte, limpieza, análisis, consentimiento, perfil instantáneo; importación de modelos RVC en ONNX) | Todo menos los modelos reales: probado con FFmpeg y vídeos reales generados |
| 4 · Conversión en tiempo real (RVC) | Implementada | Lógica probada con sesiones ONNX simuladas (formatos de entrada, frecuencia, empalme SOLA sin cortes). **Pendiente: probar con modelos reales en tu PC** |
| 4 bis · Voz instantánea en directo (MeanVC2) | Implementada (experimental) | Remuestreo en streaming, protocolo, proceso aparte (arranque, caídas, tiempo de espera), colchón con el patrón de ráfagas del modelo, caché de la huella, descargas con réplicas y SHA-256, instalación y API probados con un proceso simulado. El proceso real se ha probado solo hasta el aviso de «falta PyTorch». **Pendiente: instalar y probar con PyTorch y los pesos reales en tu PC** |
| 5 · Texto a voz (Chatterbox) | Implementada | Bucle de generación, caché KV y textos largos probados con sesiones simuladas siguiendo el script oficial. **Pendiente: probar con el modelo real en tu PC** |
| 6 · Editor y biblioteca | Hecha | Pruebas de cada operación y de la biblioteca de punta a punta en la interfaz |
| 7 · Instalador | Instalador PowerShell probado en su lógica; especificación de PyInstaller, script de Inno Setup y compilación en GitHub Actions | **Pendiente: compilar el .exe en Windows** (no se puede desde Linux) |

**No incluido (y por qué):** entrenar modelos RVC dentro de la app (requiere PyTorch con GPU; en la RX 6600 bajo Windows no hay soporte oficial). Se entrena fuera (por ejemplo, Applio) con el material que guarda VoiceLab y se importa el `.onnx`. Separación de voz y música por IA: de momento se usa limpieza clásica (filtro + reducción espectral de ruido).
