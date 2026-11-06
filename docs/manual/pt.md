# Manual do VoiceLab AI

[Español](es.md) · [English](en.md) · [Français](fr.md) · [Italiano](it.md) · **Português** · [Русский](ru.md) · [中文](zh.md) · [日本語](ja.md)

O VoiceLab AI é um estúdio de voz para Windows: muda a tua voz em tempo real, clona vozes com inteligência artificial e transforma texto em fala. Tudo funciona no teu computador, sem assinaturas nem serviços na nuvem.

> Este manual corresponde à versão 0.10. As capturas de ecrã usam perfis e dispositivos de exemplo.
>
> **A interface da aplicação está em espanhol.** Neste manual, os botões e opções aparecem como no ecrã, seguidos da tradução: **Modulador** (Modulador).

## Índice

1. [O que podes fazer](#1-o-que-podes-fazer)
2. [Requisitos](#2-requisitos)
3. [Instalação](#3-instalação)
4. [Ecrã inicial](#4-ecrã-inicial)
5. [Modulador em tempo real](#5-modulador-em-tempo-real)
6. [Vozes com inteligência artificial](#6-vozes-com-inteligência-artificial)
7. [Texto para fala](#7-texto-para-fala)
8. [Editor de áudio](#8-editor-de-áudio)
9. [Biblioteca de vozes](#9-biblioteca-de-vozes)
10. [Definições](#10-definições)
11. [Usar a tua voz no Discord, em jogos, no OBS e em editores de vídeo](#11-usar-a-tua-voz-no-discord-em-jogos-no-obs-e-em-editores-de-vídeo)
12. [Resolução de problemas](#12-resolução-de-problemas)
13. [Privacidade e uso responsável](#13-privacidade-e-uso-responsável)

---

## 1. O que podes fazer

- **Modular a tua voz em direto** com efeitos (tom, formantes, robô, rádio, eco, reverberação…) e enviá-la para qualquer programa através de um microfone virtual.
- **Clonar uma voz** a partir de um áudio ou vídeo e usá-la para ler textos (texto para fala) ou para falar em direto.
- **Treinar uma «voz fiel»**: um modelo RVC muito mais parecido, para falar em direto com pouco atraso.
- **Gravar e editar áudio**: cortar, juntar, limpar ruído, aplicar efeitos e exportar para WAV, MP3, FLAC ou OGG.
- **Organizar as tuas vozes** numa biblioteca com pastas, favoritos, exportação e cópias de segurança.

## 2. Requisitos

| | Mínimo | Recomendado |
|---|---|---|
| Sistema | Windows 10 de 64 bits | Windows 11 |
| Processador | 4 núcleos | 8 núcleos (para a voz instantânea e o treino) |
| Memória | 8 GB | 16 GB ou mais |
| Disco | 1 GB para a aplicação | +8 GB se instalares todos os modelos de IA |
| Placa gráfica | Não é necessária | Compatível com DirectX 12 (AMD, NVIDIA ou Intel) para as vozes RVC em direto |
| Microfone virtual | [VB-CABLE](https://vb-audio.com/Cable/) (gratuito) | — |

Só precisas de Internet para descarregar a aplicação e, uma vez, os modelos de IA que escolheres.

## 3. Instalação

### 3.1 Instalar a aplicação

1. Descarrega `VoiceLabAI-Setup-x.y.z.exe` da página de [versões (Releases)](https://github.com/demfisalvarez/VoiceLab-AI/releases/latest).
2. Abre-o. Se o Windows mostrar «O Windows protegeu o seu PC», clica em **Mais informações → Executar mesmo assim** (o instalador não está assinado com um certificado comercial).
3. Segue o assistente. Instala-se só para o teu utilizador e não pede permissões de administrador.
4. Abre o **VoiceLab AI** a partir do menu Iniciar ou do ambiente de trabalho.

Para desinstalar: *Definições do Windows → Aplicações → VoiceLab AI → Desinstalar*. Os teus perfis e definições ficam guardados em `%APPDATA%\VoiceLabAI`.

### 3.2 Instalar o microfone virtual (VB-CABLE)

O microfone virtual é o que permite que o Discord, os jogos ou o navegador «ouçam» a tua voz modificada.

1. Descarrega o VB-CABLE da [página oficial](https://vb-audio.com/Cable/) (gratuito, assinado pela Microsoft).
2. Descomprime o ficheiro, clica com o botão direito em `VBCABLE_Setup_x64.exe` → **Executar como administrador** → **Install Driver**.
3. Reinicia o computador.
4. Opcional: muda-lhe o nome para o reconheceres melhor. Em **Ajustes → Abrir panel de Sonido** (Definições → Abrir painel de Som), separador **Gravação**, abre **CABLE Output → Propriedades** e muda o nome para «VoiceLab AI Microphone».

### 3.3 Primeiro arranque

Ao abrir a aplicação verás o ecrã **Inicio** (Início). O cartão **Configuración inicial** (Configuração inicial) verifica o teu microfone e o microfone virtual, e indica o que falta.

## 4. Ecrã inicial

![Ecrã inicial](img/01-inicio.png)

- **Activar modulador** (Ativar modulador) liga o modulador sem sair deste ecrã. Também podes usar **Ctrl + M** a qualquer momento.
- **Abrir modulador** leva-te ao painel completo.
- **Configuración inicial** (Configuração inicial) é uma lista do que é necessário: microfone, microfone virtual, nome do dispositivo e teste de voz. Um círculo verde significa que esse passo está pronto.

Na parte de baixo da barra lateral vês sempre o estado do modulador e os medidores de entrada (**ENT**) e saída (**SAL**).

## 5. Modulador em tempo real

![Modulador em tempo real](img/02-modulador.png)

1. Carrega no grande **botão de ligar**. Passa a **Activo** (Ativo) e mostra a frequência de amostragem, o tamanho do bloco, o uso de CPU e a **latência** (o atraso da tua voz, em milissegundos).
2. Os medidores **Entrada** e **Salida** (Saída) mostram o nível do teu microfone e da voz processada (pico e RMS). O ideal é falares com a barra entre −24 e −12 dB.
3. No cartão **Entrada**:
   - **Cambiar** (Mudar) abre a lista de microfones.
   - **Ganancia de entrada** (Ganho de entrada) sobe ou desce o volume do microfone antes dos efeitos.
   - **Puerta de ruido** (Noise gate) silencia o microfone quando não falas. Ativa-a e sobe o limiar se se ouvirem ruídos de fundo (teclado, ventoinha).
4. No cartão **Voz activa** (Voz ativa) escolhes a voz em uso:
   - **Perfil guardado** muda de perfil no momento, sem parar o modulador.
   - **Guardar como perfil nuevo** (Guardar como perfil novo) guarda os efeitos atuais como um perfil.
   - **Guardar cambios en el perfil** (Guardar alterações no perfil) atualiza o perfil em uso.
   - **Voz original** retira todos os efeitos.

### 5.1 Saídas

![Saídas do modulador](img/03-salidas.png)

Podes ativar várias saídas ao mesmo tempo e alterá-las sem parar o modulador.

- **Micrófono virtual** (Microfone virtual) envia a voz processada para o VB-CABLE. É o que recebem o Discord, o Steam, os jogos, os navegadores e as videochamadas. Com **Automático**, o VoiceLab escolhe «CABLE Input» sozinho.
- **En todas las apps** (Em todas as aplicações), ativado por defeito: enquanto o modulador está ligado, o microfone virtual passa a ser o **microfone predefinido do Windows**. Assim, qualquer programa que use o microfone predefinido (jogos, editores de vídeo, o navegador…) recebe a tua voz modulada sem configurar nada. O VoiceLab continua a ouvir o teu microfone real. Ao parar o modulador ou fechar a aplicação, o Windows volta ao teu microfone de sempre.
- **Monitorización** (Monitorização) permite ouvires-te nos auscultadores. Em **Qué escuchas** (O que ouves) escolhe «Mi voz con efectos» (a minha voz com efeitos) ou «Mi micrófono original (sin efectos)» (o meu microfone original, sem efeitos). Usa auscultadores: com colunas pode haver microfonia (apito), e a aplicação avisa-te antes de a ativar.
- **Salida auxiliar** (Saída auxiliar) é uma saída a mais e independente, por exemplo um adaptador de áudio ligado a um telemóvel para chamadas.
- Cada saída tem o seu **Volumen** (Volume), um medidor, a sua latência, um contador de **Cortes** e o botão **Probar salida** (Testar saída), que reproduz um som de teste.

### 5.2 Efeitos e predefinições

![Efeitos e predefinições](img/04-efectos.png)

Em cima estão as **predefinições**: voz original, muito grave, grave, aguda, voz infantil fictícia, robô, monstro, rádio, telefone, megafone, extraterrestre e videojogo. As alterações ouvem-se de imediato e todos os valores são ajustáveis:

| Grupo | Controlos |
|---|---|
| Tono y timbre (Tom e timbre) | **Tono (pitch)** em semitons, **Formantes** (o quão «grande» ou «pequena» soa a voz) e **Voz robótica** |
| Limpieza y filtros (Limpeza e filtros) | Redução de ruído, filtro passa-altas e filtro passa-baixas |
| Graves, medios y agudos (Graves, médios e agudos) | Equalizador simples de três bandas |
| Ecualizador gráfico (Equalizador gráfico) | 10 bandas, de 31 Hz a 16 kHz |
| Dinámica (Dinâmica) | Compressor (limiar, rácio, compensação), limitador e ganho de saída |
| Color (Cor) | Saturação, distorção, lo-fi de 8 bits e modulação em anel |
| Espacio (Espaço) | Chorus, eco e reverberação |

Dica: para uma voz mais grave mas natural, baixa o **Tono** (Tom) e baixa um pouco os **Formantes**. Se baixares só o tom, a voz soa a desenho animado.

## 6. Vozes com inteligência artificial

Há três tipos de vozes de IA:

| Tipo | O que precisas | Para que serve | Semelhança |
|---|---|---|---|
| **IA instantánea** (IA instantânea) | 10–30 s de voz | Texto para fala e falar em direto (atraso de 0,25 a 0,45 s) | Boa |
| **Voz fiel** (RVC treinada) | Pelo menos 1 min de voz (melhor 10 min ou mais) e um treino de 30 min a 4 h | Falar em direto com pouco atraso | Muito alta |
| **Modelo RVC importado** | Um ficheiro `.onnx` que já tenhas | Falar em direto | Depende do modelo |

Antes de as usares, instala o motor de IA e os modelos em **Ajustes → Motor de IA y modelos** (Definições → Motor de IA e modelos). Vê [10.3](#103-motor-de-ia-e-modelos).

### 6.1 Clonar uma voz

1. Vai a **Clonar voz** e arrasta um ficheiro de áudio ou vídeo, ou clica em **elígelo en tu equipo** (escolhe-o no teu computador). Formatos aceites: MP3, WAV, FLAC, M4A, AAC, OGG, MP4, MKV, MOV e WEBM. O áudio dos vídeos é extraído automaticamente. Também podes escolher um áudio que já esteja no VoiceLab.

   ![Clonar voz: áudio de origem](img/08-clonar-subir.png)

2. **Elige el fragmento con la voz** (Escolhe o fragmento com a voz): arrasta sobre a onda para selecionar. Com **Escuchar selección** (Ouvir seleção) confirmas que só fala uma pessoa. Para a voz instantânea, o ideal são 10–30 segundos claros. Se depois quiseres **treinar uma voz fiel**, seleciona toda a voz útil (pelo menos 1 minuto, melhor 10 minutos ou mais).

   ![Clonar voz: seleção](img/09-clonar-seleccion.png)

3. Clica em **Analizar la voz** (Analisar a voz). Verás os segundos de voz útil, a relação sinal/ruído, o tom médio e o nível. Uma barra indica para que chega: 10 s para a voz instantânea, 5 min para uma voz fiel e 10 min para uma voz fiel ideal.
4. **Crear el perfil** (Criar o perfil): escreve um nome e o idioma da voz e, se quiseres, uma pasta e uma descrição. Deixa marcado **Limpiar ruido de fondo y silencios largos** (Limpar ruído de fundo e silêncios longos).
5. Indica se **Es mi propia voz** (É a minha própria voz) ou se **Tengo autorización de la persona** (Tenho autorização da pessoa). É obrigatório.
6. Clica em **Crear perfil de voz** (Criar perfil de voz).

![Clonar voz: criar o perfil](img/10-clonar-crear.png)

O perfil guarda uma referência limpa. Se a seleção tiver 1 minuto de voz ou mais, guarda também o material para treinar a voz fiel.

### 6.2 Gravar a tua voz (Crear voz)

![Criar voz](img/11-grabar.png)

1. Vai a **Crear voz** (Criar voz) e carrega no **botão vermelho** para gravar. Carrega outra vez para parar.
2. Lê as frases de **Texto para leer** (Texto para ler): cobrem todos os sons do espanhol. **Otro texto** (Outro texto) mostra outras frases.
3. As gravações aparecem em **Tus grabaciones** (As tuas gravações). Daí podes ouvi-las, abri-las no editor ou usá-las para clonar.
4. **Modificar mi voz con efectos y guardarla como perfil** (Modificar a minha voz com efeitos e guardá-la como perfil) leva-te ao modulador com a tua gravação.

Para gravar bem: divisão silenciosa, a um palmo do microfone, a falar com naturalidade e com variedade de tons e emoções.

### 6.3 Falar em direto com uma voz instantânea

![Voz instantânea em direto](img/05-voz-en-directo.png)

1. No modulador, escolhe em **Perfil guardado** um perfil do tipo «IA instantánea» (IA instantânea).
2. Da primeira vez, clica em **Instalar la voz en directo** (Instalar a voz em direto). Descarrega cerca de 1,9 GB e ocupa cerca de 2,7 GB. No fim, a aplicação mede a velocidade do teu PC e escolhe o melhor modo.
3. Marca **Hablar en directo con esta voz** (Falar em direto com esta voz) e liga o modulador. Da primeira vez com cada voz demora uns segundos a mais (calcula a impressão vocal).
4. **Modo**:
   - **Baja latencia** (Baixa latência, ≈ 0,25 s): menos atraso, mas usa cerca de três vezes mais CPU.
   - **Calidad** (Qualidade, ≈ 0,45 s): a voz fica mais parecida e gasta menos CPU.
5. Opções:
   - **Limpiar mi voz antes de convertir** (Limpar a minha voz antes de converter) tira o ruído do microfone antes da IA.
   - **Acabado de estudio** (Acabamento de estúdio) aplica de-esser, compressão e nível automático.
   - **Alta definición 48 kHz** (Alta definição 48 kHz) só funciona no modo Qualidade e se a tua CPU aguentar. É uma descarga opcional de 119 MB.
6. A linha de estado verde mostra o tempo de cálculo por bloco e a **latencia añadida** (latência adicionada) real. Se aparecer **«El procesador no llega a tiempo»** (O processador não consegue acompanhar), muda para Qualidade, desativa a alta definição ou fecha programas pesados.

A voz instantânea não precisa de treino, mas parece-se menos com a original do que uma voz fiel. O modelo foi treinado sobretudo em inglês e chinês, por isso noutros idiomas a pronúncia pode soar menos natural.

### 6.4 Treinar uma voz fiel (RVC)

![Treinar voz fiel](img/06-entrenar-voz-fiel.png)

A voz fiel é um modelo RVC treinado com o teu áudio, no teu PC. Parece-se muito mais com a voz original e em direto tem pouco atraso (cerca de 0,15–0,2 s com placa gráfica).

1. Ativa um perfil de IA instantânea criado com **1 minuto de voz ou mais** (melhor 10 minutos ou mais). Se o teu perfil foi criado com menos, cria-o de novo em **Clonar voz** com um áudio mais longo.
2. No cartão **Voz fiel (entrenada)** (Voz fiel, treinada), escolhe a duração: 30 min (teste rápido), 1 hora, **2 horas (recomendado)** ou 4 horas (máxima). Mais tempo = mais parecida.
3. Clica em **Entrenar voz fiel** (Treinar voz fiel). Da primeira vez são descarregados o PyTorch (cerca de 250 MB) e os modelos base (cerca de 0,2 GB).
4. Verás o progresso, a fase e o tempo restante. O treino usa a CPU com prioridade baixa, por isso podes continuar a usar o PC.
5. **Parar y usar lo aprendido** (Parar e usar o que aprendeu) termina o treino e cria a voz com o que aprendeu até esse momento. Se fechares a aplicação, o progresso fica guardado e depois aparece **Continuar el entrenamiento** (Continuar o treino).
6. No fim é criado um perfil novo chamado «*nome* (fiel)». Clica em **Usar la voz fiel** (Usar a voz fiel) para o ativar. Com **Seguir entrenando** (Continuar a treinar) podes melhorá-lo mais tarde.

**Ajuste de tom**: a voz fiel segue a entoação da tua voz. Se a voz original for mais aguda ou mais grave do que a tua, usa **Ajuste de tono para esta voz** (Ajuste de tom para esta voz), de −24 a +24 semitons, no cartão do perfil. Como referência, de voz masculina para feminina costuma resultar entre +8 e +12, e de feminina para masculina entre −8 e −12.

### 6.5 Importar um modelo RVC

Se já tens um modelo RVC no formato `.onnx`:

1. Instala o motor de IA e a **Base para conversión RVC** (Base para conversão RVC) em *Ajustes* (Definições).
2. Vai a **Biblioteca de voces → Importar modelo RVC** (Biblioteca de vozes → Importar modelo RVC), escreve um nome e escolhe o ficheiro.
3. Ativa-o no modulador. No cartão do perfil tens o **Ajuste de tono** (Ajuste de tom).

Só são aceites modelos `.onnx`. Os `.pth` têm de ser convertidos antes com a ferramenta de exportação do RVC.

## 7. Texto para fala

![Texto para fala](img/12-texto-a-voz.png)

1. Instala o motor de IA e o modelo **Chatterbox Multilingual** (cerca de 3,2 GB) em *Ajustes → Motor de IA y modelos* (Definições → Motor de IA e modelos).
2. Vai a **Texto a voz** (Texto para fala) e escreve ou cola o texto.
3. Escolhe a **Voz**, que pode ser qualquer perfil clonado, e o **Idioma**. Há 23 idiomas, entre eles espanhol, inglês, francês, italiano, português, russo, chinês e japonês.
4. Ajusta:
   - **Velocidad** (Velocidade).
   - **Estabilidad** (Estabilidade): mais alta = mais regular, mais baixa = mais variada.
   - **Expresividad** (Expressividade): mais emoção e ênfase.
5. Clica em **Generar audio** (Gerar áudio). A primeira geração demora mais (o modelo carrega em 1–4 minutos). **Cancelar** interrompe-a.
6. O resultado aparece em **Generaciones** (Gerações): podes ouvi-lo, abri-lo no editor ou descarregá-lo em WAV, MP3, FLAC ou OGG.

O texto para fala usa a CPU por defeito. Em *Ajustes* (Definições) podes experimentar a GPU; se falhar, a aplicação volta sozinha à CPU.

## 8. Editor de áudio

![Editor de áudio](img/13-editor.png)

- **Audios** (Áudios): importa ficheiros (ou arrasta-os); aqui aparecem também as tuas gravações e gerações. Marca vários e clica em **Unir seleccionados** (Juntar selecionados) para os juntar.
- **Onda**: arrasta para selecionar. Tens **Reproducir** (Reproduzir), **Detener** (Parar) e **Deshacer** (Desfazer).
- **Selección** (Seleção): cortar, eliminar, silenciar, dividir no cursor, fade in e fade out.
- **Volumen y limpieza** (Volume e limpeza): aplicar dB, normalizar, eliminar silêncios e reduzir ruído.
- **Efectos y tiempo** (Efeitos e tempo):
  - **Aplicar efectos** (Aplicar efeitos) usa as definições atuais do modulador ou um perfil guardado.
  - **Tempo** muda a velocidade sem mudar o tom.
  - **Velocidad** (Velocidade) muda a velocidade e o tom ao mesmo tempo.
- **Archivo** (Ficheiro): escolhe o formato (WAV, MP3, FLAC ou OGG) e clica em **Exportar**. Também podes **Duplicar**, **Usar para clonar** ou **Eliminar audio** (Eliminar áudio).

## 9. Biblioteca de vozes

![Biblioteca de vozes](img/07-biblioteca.png)

- **Pesquisa** por nome e **filtra** por pasta ou por tipo: efeitos, IA instantânea ou IA treinada (RVC).
- Cada cartão mostra o tipo, a pasta e a descrição do perfil. A estrela marca-o como favorito.
- Botões de cada cartão:
  - **Usar** ativa o perfil no modulador.
  - **Editar** muda o nome, a pasta ou a descrição.
  - **Duplicar**.
  - **Exportar** cria um ficheiro `.vlprofile` para o levar para outro PC.
  - **Eliminar**.
- **Importar** adiciona perfis exportados (`.vlprofile`). **Importar modelo RVC** adiciona modelos `.onnx`.
- **Copia de seguridad** (Cópia de segurança) guarda todos os teus perfis num único ficheiro.

## 10. Definições

### 10.1 Dispositivos de áudio

![Definições](img/14-ajustes.png)

- **Controlador de audio** (Controlador de áudio): no Windows, o **WASAPI** dá a menor latência.
- **Micrófono físico** (Microfone físico) é o microfone real que o VoiceLab ouve. É lembrado pelo nome, mesmo que mudes de porta USB.
- **Canal de entrada**: se a tua interface de áudio põe o microfone só num canal, escolhe esse canal.
- **Actualizar dispositivos** (Atualizar dispositivos) volta a procurar os dispositivos se ligares algo novo.
- O cartão **Micrófono virtual de Windows** (Microfone virtual do Windows) repete os passos de instalação do VB-CABLE e diz-te se o deteta.

### 10.2 Desempenho e latência

- **Frecuencia de muestreo** (Frequência de amostragem): 48 000 Hz (recomendado) ou 44 100 Hz.
- **Tamaño de bloque** (Tamanho do bloco): mais pequeno = menos atraso, mas mais risco de cortes. 256 amostras (5,3 ms) funcionam bem em quase todos os computadores.
- **Margen anticortes** (Margem anticortes): sobe-a se ouvires estalidos.

### 10.3 Motor de IA e modelos

![Motor de IA e modelos](img/15-modelos-ia.png)

Os modelos descarregam-se uma vez a partir do Hugging Face (grátis e sem conta) e depois funcionam sem Internet. Cada descarga é verificada e pode ser retomada se for interrompida.

| Componente | Tamanho | Para que serve |
|---|---|---|
| Motor de IA (ONNX Runtime e tokenizers) | ~60 MB | Necessário para tudo o que é IA |
| Chatterbox Multilingual | ~3,2 GB | Texto para fala e clonagem instantânea |
| Base para conversão RVC (ContentVec + RMVPE) | ~0,55 GB | Vozes RVC em direto (importadas ou treinadas) |
| Base para treinar vozes fiéis (RVC v2, 40 kHz) | ~0,21 GB | Treinar uma voz fiel |
| AP-BWE (alta definição) | ~0,12 GB | Opcional, para a voz instantânea no modo Qualidade |
| Voz instantânea em direto (MeanVC2 + PyTorch para CPU) | ~1,9 GB de descarga | Falar em direto com vozes instantâneas |

Também escolhes onde corre cada parte:

- **Texto a voz se ejecuta en** (O texto para fala corre em): CPU (recomendado) ou GPU.
- **Voces RVC en directo se ejecutan en** (As vozes RVC em direto correm em): GPU com DirectML (recomendado se tiveres placa gráfica) ou CPU.

## 11. Usar a tua voz no Discord, em jogos, no OBS e em editores de vídeo

Com **En todas las apps** (Em todas as aplicações) ativado (vê [5.1](#51-saídas)), qualquer programa que use o microfone predefinido do Windows já recebe a tua voz modulada. Alguns programas precisam de mais um passo:

- **Discord**:
  1. Em *Configurações de utilizador → Voz e vídeo*, escolhe como **dispositivo de entrada** «CABLE Output» (ou «VoiceLab AI Microphone») ou «Padrão».
  2. Põe a **supressão de ruído** em **Nenhuma**.
  3. Desativa o **cancelamento de eco**, o **controlo automático de ganho** e a **atividade de voz avançada**. Com as vozes de IA, estes filtros fazem-nas soar robóticas.
- **Jogos**: quase todos usam o microfone predefinido. Se um jogo só lê o microfone ao arrancar, abre-o com o modulador já ligado.
- **OBS Studio**: adiciona uma fonte **Captura de entrada de áudio** com «CABLE Output», ou usa «Padrão».
- **Editores de vídeo** (DaVinci Resolve, Premiere, CapCut…): para gravar uma narração com efeitos, escolhe «CABLE Output» ou o microfone predefinido como entrada de gravação.
- **Navegador e videochamadas** (Meet, Teams, Zoom): escolhe «CABLE Output» ou «Padrão» nas definições de áudio de cada serviço.

## 12. Resolução de problemas

| Problema | O que fazer |
|---|---|
| Ninguém me ouve | Confirma que o modulador está **Activo** (Ativo) e que a saída **Micrófono virtual** (Microfone virtual) está ligada. No outro programa, escolhe «CABLE Output» ou «Padrão». |
| «Microfone virtual não detetado» | Instala o VB-CABLE como administrador e reinicia o PC. Depois clica em **Actualizar dispositivos** (Atualizar dispositivos) em *Ajustes* (Definições). |
| A voz de IA soa robótica no Discord | Desativa os filtros de voz do Discord (vê [11](#11-usar-a-tua-voz-no-discord-em-jogos-no-obs-e-em-editores-de-vídeo)). |
| Cortes, estalidos ou «El procesador no llega a tiempo» (O processador não consegue acompanhar) | Usa o modo **Calidad** (Qualidade) sem alta definição e fecha programas pesados. Sobe a **Margen anticortes** (Margem anticortes) ou o **Tamaño de bloque** (Tamanho do bloco). |
| Muito atraso | Usa **Baja latencia** (Baixa latência) se a tua CPU aguentar, ou uma **voz fiel** com a GPU. A latência real aparece no modulador. |
| Apito ou microfonia | Usa auscultadores para a monitorização, não colunas. |
| Ouve-se ruído de fundo | Ativa a **Puerta de ruido** (Noise gate) e a **Reducción de ruido** (Redução de ruído), ou **Limpiar mi voz antes de convertir** (Limpar a minha voz antes de converter) nas vozes de IA. |
| O texto para fala demora da primeira vez | É normal: o modelo carrega em 1–4 minutos. As gerações seguintes são mais rápidas. |
| Um programa continua com o microfone antigo | Alguns programas só leem o microfone ao abrir: fecha-o e abre-o de novo com o modulador ligado. |
| Preciso dos registos para pedir ajuda | Estão em `%APPDATA%\VoiceLabAI\logs` (`voicelab.log`, `voz-instantanea.log` e `entrenamiento.log`). |

## 13. Privacidade e uso responsável

- **Tudo é processado no teu PC.** A tua voz, os teus perfis e as tuas gravações não são enviados para nenhum servidor. A Internet só é usada para descarregar a aplicação e os modelos.
- **Clona apenas a tua própria voz ou vozes de pessoas que te tenham dado autorização.** A aplicação pede que o confirmes em cada perfil.
- Não uses vozes clonadas para enganar, fazer-te passar por alguém ou cometer fraudes. Em muitos países é ilegal.
- Os modelos de IA têm as suas próprias licenças (MIT e Apache 2.0). Encontras-las em *Ajustes → Motor de IA y modelos* (Definições → Motor de IA e modelos) e no [README](../../README.md).

---

Atalho: **Ctrl + M** liga e desliga o modulador. Dados da aplicação: `%APPDATA%\VoiceLabAI`.
