# Manuale di VoiceLab AI

[Español](es.md) · [English](en.md) · [Français](fr.md) · **Italiano** · [Português](pt.md) · [Русский](ru.md) · [中文](zh.md) · [日本語](ja.md)

VoiceLab AI è uno studio vocale per Windows: cambia la tua voce in tempo reale, clona voci con l'intelligenza artificiale e trasforma il testo in voce. Tutto funziona sul tuo computer, senza abbonamenti né servizi cloud.

> Questo manuale si riferisce alla versione 0.10. Le schermate usano profili e dispositivi di esempio.
>
> **L'interfaccia dell'app è in spagnolo.** In questo manuale pulsanti e opzioni appaiono come sullo schermo, seguiti dalla traduzione: **Modulador** (Modulatore).

## Indice

1. [Cosa puoi fare](#1-cosa-puoi-fare)
2. [Requisiti](#2-requisiti)
3. [Installazione](#3-installazione)
4. [Schermata iniziale](#4-schermata-iniziale)
5. [Modulatore in tempo reale](#5-modulatore-in-tempo-reale)
6. [Voci con intelligenza artificiale](#6-voci-con-intelligenza-artificiale)
7. [Sintesi vocale](#7-sintesi-vocale)
8. [Editor audio](#8-editor-audio)
9. [Libreria delle voci](#9-libreria-delle-voci)
10. [Impostazioni](#10-impostazioni)
11. [Usare la tua voce su Discord, nei giochi, in OBS e negli editor video](#11-usare-la-tua-voce-su-discord-nei-giochi-in-obs-e-negli-editor-video)
12. [Risoluzione dei problemi](#12-risoluzione-dei-problemi)
13. [Privacy e uso responsabile](#13-privacy-e-uso-responsabile)

---

## 1. Cosa puoi fare

- **Modificare la voce in diretta** con effetti (tono, formanti, robot, radio, eco, riverbero…) e inviarla a qualsiasi programma tramite un microfono virtuale.
- **Clonare una voce** da un file audio o video e usarla per leggere testi (sintesi vocale) o per parlare in diretta.
- **Addestrare una «voce fedele»**: un modello RVC molto più somigliante, per parlare in diretta con poco ritardo.
- **Registrare e modificare l'audio**: tagliare, unire, ridurre il rumore, applicare effetti ed esportare in WAV, MP3, FLAC o OGG.
- **Organizzare le voci** in una libreria con cartelle, preferiti, esportazione e backup.

## 2. Requisiti

| | Minimo | Consigliato |
|---|---|---|
| Sistema | Windows 10 a 64 bit | Windows 11 |
| Processore | 4 core | 8 core (per la voce istantanea e l'addestramento) |
| Memoria | 8 GB | 16 GB o più |
| Disco | 1 GB per l'app | +8 GB se installi tutti i modelli di IA |
| Scheda video | Non necessaria | Compatibile DirectX 12 (AMD, NVIDIA o Intel) per le voci RVC in diretta |
| Microfono virtuale | [VB-CABLE](https://vb-audio.com/Cable/) (gratuito) | — |

Internet serve solo per scaricare l'app e, una volta, i modelli di IA che scegli.

## 3. Installazione

### 3.1 Installare l'app

1. Scarica `VoiceLabAI-Setup-x.y.z.exe` dalla pagina delle [versioni (Releases)](https://github.com/demfisalvarez/VoiceLab-AI/releases/latest).
2. Avvialo. Se Windows mostra «PC protetto da Windows», fai clic su **Ulteriori informazioni → Esegui comunque** (il programma di installazione non è firmato con un certificato commerciale).
3. Segui la procedura guidata. Si installa solo per il tuo utente e non richiede permessi di amministratore.
4. Apri **VoiceLab AI** dal menu Start o dal desktop.

Per disinstallarla: *Impostazioni di Windows → App → VoiceLab AI → Disinstalla*. Profili e impostazioni sono salvati in `%APPDATA%\VoiceLabAI`.

### 3.2 Installare il microfono virtuale (VB-CABLE)

Il microfono virtuale permette a Discord, ai giochi o al browser di «sentire» la tua voce modificata.

1. Scarica VB-CABLE dalla [pagina ufficiale](https://vb-audio.com/Cable/) (gratuito, firmato da Microsoft).
2. Estrai l'archivio, fai clic destro su `VBCABLE_Setup_x64.exe` → **Esegui come amministratore** → **Install Driver**.
3. Riavvia il computer.
4. Facoltativo: rinominalo per riconoscerlo meglio. In **Ajustes → Abrir panel de Sonido** (Impostazioni → Apri pannello Audio), scheda **Registrazione**, apri **CABLE Output → Proprietà** e rinominalo «VoiceLab AI Microphone».

### 3.3 Primo avvio

All'apertura vedrai la schermata **Inicio** (Home). La scheda **Configuración inicial** (Configurazione iniziale) controlla il microfono e il microfono virtuale e ti indica cosa manca.

## 4. Schermata iniziale

![Schermata iniziale](img/01-inicio.png)

- **Activar modulador** (Attiva modulatore) lo accende senza lasciare questa schermata. Puoi anche usare **Ctrl + M** in qualsiasi momento.
- **Abrir modulador** (Apri modulatore) porta al pannello completo.
- **Configuración inicial** (Configurazione iniziale) elenca ciò che serve: microfono, microfono virtuale, nome del dispositivo e prova della voce. Un cerchio verde indica che il passaggio è pronto.

In fondo alla barra laterale vedi sempre lo stato del modulatore e gli indicatori di ingresso (**ENT**) e di uscita (**SAL**).

## 5. Modulatore in tempo reale

![Modulatore in tempo reale](img/02-modulador.png)

1. Premi il grande **pulsante di accensione**. Diventa **Activo** (Attivo) e mostra la frequenza di campionamento, la dimensione del blocco, l'uso della CPU e la **latenza** (il ritardo della voce, in millisecondi).
2. Gli indicatori **Entrada** (Ingresso) e **Salida** (Uscita) mostrano il livello del microfono e della voce elaborata (picco e RMS). L'ideale è parlare con la barra tra −24 e −12 dB.
3. Nella scheda **Entrada** (Ingresso):
   - **Cambiar** (Cambia) apre l'elenco dei microfoni.
   - **Ganancia de entrada** (Guadagno di ingresso) alza o abbassa il volume del microfono prima degli effetti.
   - **Puerta de ruido** (Noise gate) silenzia il microfono quando non parli. Attivala e alza la soglia se passano rumori di fondo (tastiera, ventola).
4. Nella scheda **Voz activa** (Voce attiva) scegli la voce in uso:
   - **Perfil guardado** (Profilo salvato) cambia profilo all'istante, senza fermare il modulatore.
   - **Guardar como perfil nuevo** (Salva come nuovo profilo) salva gli effetti attuali come profilo.
   - **Guardar cambios en el perfil** (Salva modifiche al profilo) aggiorna il profilo in uso.
   - **Voz original** (Voce originale) toglie tutti gli effetti.

### 5.1 Uscite

![Uscite del modulatore](img/03-salidas.png)

Puoi attivare più uscite contemporaneamente e cambiarle senza fermare il modulatore.

- **Micrófono virtual** (Microfono virtuale) invia la voce elaborata a VB-CABLE. È ciò che ricevono Discord, Steam, i giochi, i browser e le videochiamate. Con **Automático** (Automatico), VoiceLab sceglie da solo «CABLE Input».
- **En todas las apps** (In tutte le app), attivo per impostazione predefinita: mentre il modulatore è acceso, il microfono virtuale diventa il **microfono predefinito di Windows**. Così qualsiasi programma che usa il microfono predefinito (giochi, editor video, browser…) riceve la voce modulata senza configurare nulla. VoiceLab continua ad ascoltare il tuo microfono reale. Quando fermi il modulatore o chiudi l'app, Windows torna al microfono di sempre.
- **Monitorización** (Monitoraggio) ti permette di ascoltarti in cuffia. In **Qué escuchas** (Cosa ascolti) scegli «Mi voz con efectos» (la mia voce con effetti) o «Mi micrófono original (sin efectos)» (il mio microfono originale, senza effetti). Usa le cuffie: con gli altoparlanti si può creare il feedback (fischio), e l'app ti avvisa prima di attivarlo.
- **Salida auxiliar** (Uscita ausiliaria) è un'uscita in più e indipendente, ad esempio un adattatore audio collegato a un telefono per le chiamate.
- Ogni uscita ha il suo **Volumen** (Volume), un indicatore, la sua latenza, un contatore di **Cortes** (Interruzioni) e il pulsante **Probar salida** (Prova uscita), che riproduce un suono di prova.

### 5.2 Effetti e preset

![Effetti e preset](img/04-efectos.png)

In alto ci sono i **preset**: voce originale, molto grave, grave, acuta, voce infantile di fantasia, robot, mostro, radio, telefono, megafono, alieno e videogioco. Le modifiche si sentono subito e tutti i valori sono regolabili:

| Gruppo | Controlli |
|---|---|
| Tono y timbre (Tono e timbro) | **Tono (pitch)** in semitoni, **Formantes** (Formanti: quanto la voce suona «grande» o «piccola») e **Voz robótica** (Voce robotica) |
| Limpieza y filtros (Pulizia e filtri) | Riduzione del rumore, filtro passa-alto e filtro passa-basso |
| Graves, medios y agudos (Bassi, medi e alti) | Equalizzatore semplice a tre bande |
| Ecualizador gráfico (Equalizzatore grafico) | 10 bande, da 31 Hz a 16 kHz |
| Dinámica (Dinamica) | Compressore (soglia, rapporto, compensazione), limitatore e guadagno di uscita |
| Color (Colore) | Saturazione, distorsione, lo-fi a 8 bit e modulazione ad anello |
| Espacio (Spazio) | Chorus, eco e riverbero |

Consiglio: per una voce più grave ma naturale, abbassa il **Tono** e abbassa un po' i **Formantes** (Formanti). Se abbassi solo il tono, la voce sembra quella di un cartone animato.

## 6. Voci con intelligenza artificiale

Esistono tre tipi di voci di IA:

| Tipo | Cosa serve | A cosa serve | Somiglianza |
|---|---|---|---|
| **IA instantánea** (IA istantanea) | 10–30 s di voce | Sintesi vocale e parlare in diretta (ritardo da 0,25 a 0,45 s) | Buona |
| **Voz fiel** (Voce fedele, RVC addestrata) | Almeno 1 min di voce (meglio 10 min o più) e da 30 min a 4 h di addestramento | Parlare in diretta con poco ritardo | Molto alta |
| **Modello RVC importato** | Un file `.onnx` che hai già | Parlare in diretta | Dipende dal modello |

Prima di usarle, installa il motore di IA e i modelli in **Ajustes → Motor de IA y modelos** (Impostazioni → Motore di IA e modelli). Vedi [10.3](#103-motore-di-ia-e-modelli).

### 6.1 Clonare una voce

1. Vai su **Clonar voz** (Clona voce) e trascina un file audio o video, oppure fai clic su **elígelo en tu equipo** (sceglilo sul computer). Formati supportati: MP3, WAV, FLAC, M4A, AAC, OGG, MP4, MKV, MOV e WEBM. L'audio dei video viene estratto automaticamente. Puoi anche scegliere un audio già presente in VoiceLab.

   ![Clona voce: audio di origine](img/08-clonar-subir.png)

2. **Elige el fragmento con la voz** (Scegli il frammento con la voce): trascina sulla forma d'onda per selezionare. Con **Escuchar selección** (Ascolta selezione) verifichi che parli una sola persona. Per la voce istantanea l'ideale sono 10–30 secondi chiari. Se poi vuoi **addestrare una voce fedele**, seleziona tutta la voce utile (almeno 1 minuto, meglio 10 minuti o più).

   ![Clona voce: selezione](img/09-clonar-seleccion.png)

3. Fai clic su **Analizar la voz** (Analizza la voce). Vedrai i secondi di voce utile, il rapporto segnale/rumore, il tono medio e il livello. Una barra indica a cosa basta: 10 s per la voce istantanea, 5 min per una voce fedele e 10 min per una voce fedele ideale.
4. **Crear el perfil** (Crea il profilo): scrivi un nome e la lingua della voce e, se vuoi, una cartella e una descrizione. Lascia selezionato **Limpiar ruido de fondo y silencios largos** (Rimuovi rumore di fondo e silenzi lunghi).
5. Indica se **Es mi propia voz** (È la mia voce) o se **Tengo autorización de la persona** (Ho l'autorizzazione della persona). È obbligatorio.
6. Fai clic su **Crear perfil de voz** (Crea profilo vocale).

![Clona voce: crea il profilo](img/10-clonar-crear.png)

Il profilo conserva un riferimento pulito. Se la selezione ha 1 minuto di voce o più, conserva anche il materiale per addestrare la voce fedele.

### 6.2 Registrare la tua voce (Crear voz)

![Crea voce](img/11-grabar.png)

1. Vai su **Crear voz** (Crea voce) e premi il **pulsante rosso** per registrare. Premilo di nuovo per fermarti.
2. Leggi le frasi di **Texto para leer** (Testo da leggere): coprono tutti i suoni dello spagnolo. **Otro texto** (Altro testo) mostra altre frasi.
3. Le registrazioni appaiono in **Tus grabaciones** (Le tue registrazioni). Da lì puoi ascoltarle, aprirle nell'editor o usarle per clonare.
4. **Modificar mi voz con efectos y guardarla como perfil** (Modifica la mia voce con effetti e salvala come profilo) ti porta al modulatore con la registrazione.

Per registrare bene: stanza silenziosa, a un palmo dal microfono, parlando con naturalezza e con varietà di toni ed emozioni.

### 6.3 Parlare in diretta con una voce istantanea

![Voce istantanea in diretta](img/05-voz-en-directo.png)

1. Nel modulatore, scegli in **Perfil guardado** (Profilo salvato) un profilo di tipo «IA instantánea» (IA istantanea).
2. La prima volta, fai clic su **Instalar la voz en directo** (Installa la voce in diretta). Scarica circa 1,9 GB e occupa circa 2,7 GB. Alla fine, l'app misura la velocità del PC e sceglie la modalità migliore.
3. Seleziona **Hablar en directo con esta voz** (Parla in diretta con questa voce) e accendi il modulatore. La prima volta con ogni voce servono alcuni secondi in più (calcola l'impronta vocale).
4. **Modo** (Modalità):
   - **Baja latencia** (Bassa latenza, ≈ 0,25 s): meno ritardo, ma usa circa tre volte più CPU.
   - **Calidad** (Qualità, ≈ 0,45 s): voce più somigliante e meno CPU.
5. Opzioni:
   - **Limpiar mi voz antes de convertir** (Pulisci la mia voce prima della conversione) toglie il rumore del microfono prima dell'IA.
   - **Acabado de estudio** (Finitura da studio) aggiunge de-esser, compressione e livello automatico.
   - **Alta definición 48 kHz** (Alta definizione 48 kHz) funziona solo in modalità Qualità e se la CPU regge. È un download facoltativo di 119 MB.
6. La riga di stato verde mostra il tempo di calcolo per blocco e la **latencia añadida** (latenza aggiunta) reale. Se appare **«El procesador no llega a tiempo»** (Il processore non riesce a stare al passo), passa a Qualità, disattiva l'alta definizione o chiudi i programmi pesanti.

La voce istantanea non richiede addestramento, ma somiglia meno all'originale rispetto a una voce fedele. Il modello è stato addestrato soprattutto in inglese e cinese: in altre lingue la pronuncia può sembrare meno naturale.

### 6.4 Addestrare una voce fedele (RVC)

![Addestra una voce fedele](img/06-entrenar-voz-fiel.png)

La voce fedele è un modello RVC addestrato con il tuo audio, sul tuo PC. Somiglia molto di più alla voce originale e in diretta ha poco ritardo (circa 0,15–0,2 s con una scheda video).

1. Attiva un profilo di IA istantanea creato con **1 minuto di voce o più** (meglio 10 minuti o più). Se il profilo è stato creato con meno, ricrealo in **Clonar voz** (Clona voce) con un audio più lungo.
2. Nella scheda **Voz fiel (entrenada)** (Voce fedele, addestrata), scegli la durata: 30 min (prova rapida), 1 ora, **2 horas (recomendado)** (2 ore, consigliato) o 4 ore (massima). Più tempo = più somiglianza.
3. Fai clic su **Entrenar voz fiel** (Addestra voce fedele). La prima volta vengono scaricati PyTorch (circa 250 MB) e i modelli di base (circa 0,2 GB).
4. Vedrai l'avanzamento, la fase e il tempo rimanente. L'addestramento usa la CPU con priorità bassa, quindi puoi continuare a usare il PC.
5. **Parar y usar lo aprendido** (Ferma e usa quanto appreso) interrompe l'addestramento e crea la voce con ciò che ha imparato fin lì. Se chiudi l'app, i progressi vengono salvati e in seguito appare **Continuar el entrenamiento** (Continua l'addestramento).
6. Alla fine viene creato un nuovo profilo «*nome* (fiel)». Fai clic su **Usar la voz fiel** (Usa la voce fedele) per attivarlo. Puoi migliorarlo più avanti con **Seguir entrenando** (Continua ad addestrare).

**Regolazione del tono**: la voce fedele segue l'intonazione della tua voce. Se la voce originale è più acuta o più grave della tua, usa **Ajuste de tono para esta voz** (Regolazione del tono per questa voce), da −24 a +24 semitoni, nella scheda del profilo. Come riferimento, da voce maschile a femminile di solito vanno bene tra +8 e +12; da femminile a maschile tra −8 e −12.

### 6.5 Importare un modello RVC

Se hai già un modello RVC in formato `.onnx`:

1. Installa il motore di IA e la **Base para conversión RVC** (Base per la conversione RVC) in *Ajustes* (Impostazioni).
2. Vai su **Biblioteca de voces → Importar modelo RVC** (Libreria delle voci → Importa modello RVC), scrivi un nome e scegli il file.
3. Attivalo nel modulatore. La scheda del profilo ha l'**Ajuste de tono** (Regolazione del tono).

Sono supportati solo i modelli `.onnx`. I `.pth` vanno prima convertiti con lo strumento di esportazione di RVC.

## 7. Sintesi vocale

![Sintesi vocale](img/12-texto-a-voz.png)

1. Installa il motore di IA e il modello **Chatterbox Multilingual** (circa 3,2 GB) in *Ajustes → Motor de IA y modelos* (Impostazioni → Motore di IA e modelli).
2. Vai su **Texto a voz** (Sintesi vocale) e scrivi o incolla il testo.
3. Scegli la **Voz** (Voce), cioè qualsiasi profilo clonato, e l'**Idioma** (Lingua). Ci sono 23 lingue, tra cui spagnolo, inglese, francese, italiano, portoghese, russo, cinese e giapponese.
4. Regola:
   - **Velocidad** (Velocità).
   - **Estabilidad** (Stabilità): più alta = più regolare, più bassa = più varia.
   - **Expresividad** (Espressività): più emozione ed enfasi.
5. Fai clic su **Generar audio** (Genera audio). La prima generazione richiede più tempo (il modello si carica in 1–4 minuti). **Cancelar** (Annulla) la interrompe.
6. Il risultato appare in **Generaciones** (Generazioni): puoi ascoltarlo, aprirlo nell'editor o scaricarlo in WAV, MP3, FLAC o OGG.

La sintesi vocale usa la CPU per impostazione predefinita. In *Ajustes* (Impostazioni) puoi provare la GPU; se non funziona, l'app torna da sola alla CPU.

## 8. Editor audio

![Editor audio](img/13-editor.png)

- **Audios**: importa file (o trascinali); qui compaiono anche registrazioni e generazioni. Selezionane più di uno e fai clic su **Unir seleccionados** (Unisci selezionati) per unirli.
- **Forma d'onda**: trascina per selezionare. Hai **Reproducir** (Riproduci), **Detener** (Ferma) e **Deshacer** (Annulla).
- **Selección** (Selezione): taglia, elimina, silenzia, dividi al cursore, dissolvenza in entrata e in uscita.
- **Volumen y limpieza** (Volume e pulizia): applica dB, normalizza, elimina silenzi e riduci rumore.
- **Efectos y tiempo** (Effetti e tempo):
  - **Aplicar efectos** (Applica effetti) usa le impostazioni attuali del modulatore o un profilo salvato.
  - **Tempo** cambia la velocità senza cambiare il tono.
  - **Velocidad** (Velocità) cambia velocità e tono insieme.
- **Archivo** (File): scegli il formato (WAV, MP3, FLAC o OGG) e fai clic su **Exportar** (Esporta). Puoi anche **Duplicar** (Duplica), **Usar para clonar** (Usa per clonare) o **Eliminar audio** (Elimina audio).

## 9. Libreria delle voci

![Libreria delle voci](img/07-biblioteca.png)

- **Cerca** per nome e **filtra** per cartella o per tipo: effetti, IA istantanea o IA addestrata (RVC).
- Ogni scheda mostra tipo, cartella e descrizione del profilo. La stella lo segna come preferito.
- Pulsanti di ogni scheda:
  - **Usar** (Usa) attiva il profilo nel modulatore.
  - **Modifica** cambia nome, cartella o descrizione.
  - **Duplica**.
  - **Esporta** crea un file `.vlprofile` per passarlo a un altro PC.
  - **Elimina**.
- **Importar** (Importa) aggiunge profili esportati (`.vlprofile`). **Importar modelo RVC** (Importa modello RVC) aggiunge modelli `.onnx`.
- **Copia de seguridad** (Backup) salva tutti i profili in un unico file.

## 10. Impostazioni

### 10.1 Dispositivi audio

![Impostazioni](img/14-ajustes.png)

- **Controlador de audio** (Driver audio): su Windows, **WASAPI** offre la latenza più bassa.
- **Micrófono físico** (Microfono fisico) è il microfono reale che VoiceLab ascolta. Viene ricordato per nome, anche se cambi porta USB.
- **Canal de entrada** (Canale di ingresso): se l'interfaccia audio mette il microfono su un solo canale, scegli quel canale.
- **Actualizar dispositivos** (Aggiorna dispositivi) cerca di nuovo i dispositivi se colleghi qualcosa di nuovo.
- La scheda **Micrófono virtual de Windows** (Microfono virtuale di Windows) ripete i passaggi di installazione di VB-CABLE e ti dice se viene rilevato.

### 10.2 Prestazioni e latenza

- **Frecuencia de muestreo** (Frequenza di campionamento): 48.000 Hz (consigliato) o 44.100 Hz.
- **Tamaño de bloque** (Dimensione del blocco): più piccolo = meno ritardo, ma più rischio di interruzioni. 256 campioni (5,3 ms) vanno bene su quasi tutti i computer.
- **Margen anticortes** (Margine anti-interruzioni): alzalo se senti dei clic.

### 10.3 Motore di IA e modelli

![Motore di IA e modelli](img/15-modelos-ia.png)

I modelli si scaricano una volta da Hugging Face (gratis e senza account) e poi funzionano senza Internet. Ogni download viene verificato e può riprendere se si interrompe.

| Componente | Dimensione | A cosa serve |
|---|---|---|
| Motore di IA (ONNX Runtime e tokenizers) | ~60 MB | Necessario per tutte le funzioni di IA |
| Chatterbox Multilingual | ~3,2 GB | Sintesi vocale e clonazione istantanea |
| Base per la conversione RVC (ContentVec + RMVPE) | ~0,55 GB | Voci RVC in diretta (importate o addestrate) |
| Base per addestrare voci fedeli (RVC v2, 40 kHz) | ~0,21 GB | Addestrare una voce fedele |
| AP-BWE (alta definizione) | ~0,12 GB | Facoltativo, voce istantanea in modalità Qualità |
| Voce istantanea in diretta (MeanVC2 + PyTorch per CPU) | ~1,9 GB da scaricare | Parlare in diretta con voci istantanee |

Scegli anche dove viene eseguita ogni parte:

- **Texto a voz se ejecuta en** (La sintesi vocale viene eseguita su): CPU (consigliato) o GPU.
- **Voces RVC en directo se ejecutan en** (Le voci RVC in diretta vengono eseguite su): GPU con DirectML (consigliato se hai una scheda video) o CPU.

## 11. Usare la tua voce su Discord, nei giochi, in OBS e negli editor video

Con **En todas las apps** (In tutte le app) attivo (vedi [5.1](#51-uscite)), qualsiasi programma che usa il microfono predefinito di Windows riceve già la voce modulata. Alcuni programmi richiedono un passaggio in più:

- **Discord**:
  1. In *Impostazioni utente → Voce e video*, imposta come **dispositivo di ingresso** «CABLE Output» (o «VoiceLab AI Microphone») oppure «Predefinito».
  2. Imposta la **soppressione del rumore** su **Nessuna**.
  3. Disattiva la **cancellazione dell'eco**, il **controllo automatico del guadagno** e il **rilevamento avanzato della voce**. Con le voci di IA questi filtri le fanno sembrare robotiche.
- **Giochi**: quasi tutti usano il microfono predefinito. Se un gioco legge il microfono solo all'avvio, aprilo con il modulatore già acceso.
- **OBS Studio**: aggiungi una fonte **Cattura ingresso audio** con «CABLE Output», oppure usa «Predefinito».
- **Editor video** (DaVinci Resolve, Premiere, CapCut…): per registrare una voce fuori campo con effetti, scegli «CABLE Output» o il microfono predefinito come ingresso di registrazione.
- **Browser e videochiamate** (Meet, Teams, Zoom): scegli «CABLE Output» o «Predefinito» nelle impostazioni audio di ciascun servizio.

## 12. Risoluzione dei problemi

| Problema | Cosa fare |
|---|---|
| Gli altri non mi sentono | Controlla che il modulatore sia **Activo** (Attivo) e che l'uscita **Micrófono virtual** (Microfono virtuale) sia accesa. Nell'altro programma scegli «CABLE Output» o «Predefinito». |
| «Microfono virtuale non rilevato» | Installa VB-CABLE come amministratore e riavvia il PC. Poi fai clic su **Actualizar dispositivos** (Aggiorna dispositivi) in *Ajustes* (Impostazioni). |
| La voce di IA sembra robotica su Discord | Disattiva i filtri vocali di Discord (vedi [11](#11-usare-la-tua-voce-su-discord-nei-giochi-in-obs-e-negli-editor-video)). |
| Interruzioni, clic o «El procesador no llega a tiempo» (Il processore non riesce a stare al passo) | Usa la modalità **Calidad** (Qualità) senza alta definizione e chiudi i programmi pesanti. Alza il **Margen anticortes** (Margine anti-interruzioni) o la **Tamaño de bloque** (Dimensione del blocco). |
| Troppo ritardo | Usa **Baja latencia** (Bassa latenza) se la CPU regge, oppure una **voce fedele** con la GPU. La latenza reale appare nel modulatore. |
| Fischio o feedback | Usa le cuffie per il monitoraggio, non gli altoparlanti. |
| Si sente rumore di fondo | Attiva la **Puerta de ruido** (Noise gate) e la **Reducción de ruido** (Riduzione del rumore), oppure **Limpiar mi voz antes de convertir** (Pulisci la mia voce prima della conversione) per le voci di IA. |
| La sintesi vocale è lenta la prima volta | È normale: il modello si carica in 1–4 minuti. Le generazioni successive sono più veloci. |
| Un programma usa ancora il vecchio microfono | Alcuni programmi leggono il microfono solo all'apertura: chiudilo e riaprilo con il modulatore acceso. |
| Mi servono i log per chiedere aiuto | Si trovano in `%APPDATA%\VoiceLabAI\logs` (`voicelab.log`, `voz-instantanea.log` e `entrenamiento.log`). |

## 13. Privacy e uso responsabile

- **Tutto viene elaborato sul tuo PC.** Voce, profili e registrazioni non vengono inviati a nessun server. Internet serve solo per scaricare l'app e i modelli.
- **Clona solo la tua voce o quella di persone che ti hanno dato il permesso.** L'app chiede di confermarlo per ogni profilo.
- Non usare voci clonate per ingannare, impersonare qualcuno o commettere frodi. In molti paesi è illegale.
- I modelli di IA hanno le proprie licenze (MIT e Apache 2.0). Le trovi in *Ajustes → Motor de IA y modelos* (Impostazioni → Motore di IA e modelli) e nel [README](../../README.md).

---

Scorciatoia: **Ctrl + M** accende e spegne il modulatore. Dati dell'app: `%APPDATA%\VoiceLabAI`.
