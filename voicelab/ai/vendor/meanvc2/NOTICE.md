# Código de terceros incluido (sin modificar salvo lo indicado)

Este directorio lo ejecuta **solo** el proceso aparte de «Voz instantánea en
directo» (`voicelab/ai/meanvc_worker.py`), con su propio entorno de PyTorch.
La aplicación principal nunca lo importa.

## MeanVC2 — ASLP-lab, Northwestern Polytechnical University
- Origen: https://github.com/ASLP-lab/MeanVC2 (commit 13acf84c1bf135ea5edad9c245b345289b06b33e)
- Licencia: Apache License 2.0 (declarada en el README del proyecto; texto en `LICENSE-APACHE-2.0.txt`)
- Archivos: `runtime/run_rt.py`, `runtime/src/*.py`, `src/config/*.json` (copias literales)
- Pesos: se descargan aparte desde https://huggingface.co/ASLP-lab/MeanVC2
- Aviso de los autores: úsese solo con el consentimiento de las personas cuya voz
  se convierte o se usa como referencia; prohibido suplantar, defraudar o engañar.

## s3prl (subconjunto) — https://github.com/s3prl/s3prl (commit ec8064b5889f81ca460fbe2c094ce576a6f120b7)
- Licencia: Apache License 2.0. `upstream/wavlm/*.py` son de Microsoft (licencia MIT, ver cabeceras).
- Archivos copiados literalmente: `upstream/interfaces.py`, `upstream/wavlm/{WavLM,modules,expert}.py`.
- `utility/helper.py` es un sustituto de 5 líneas (solo la función `show`), y los
  `__init__.py` están vacíos para no arrastrar las dependencias del paquete completo.

## Pesos del codificador de hablante (WavLM-Large + ECAPA-TDNN, UniSpeech/Microsoft)
- `wavlm_large_finetune.pth`, publicado por Microsoft (UniSpeech) en Google Drive;
  la app lo descarga de una réplica en Hugging Face y comprueba su SHA-256.
