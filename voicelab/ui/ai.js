/* Fases 4 y 5: motor de IA, modelos, texto a voz y voces RVC. */
(function () {
  'use strict';
  let VL, $, $$, ai = null, profiles = [];
  const job = (r) => window.VLStudio.runJob(r);
  const gb = (x) => String(x).replace('.', ',');

  async function refresh() {
    const r = await VL.call('ai_status');
    if (r.ok) ai = r.ai;
    const p = await VL.call('list_profiles');
    if (p.ok) profiles = p.profiles;
    renderPanel(); renderTTS(); renderVoice();
  }

  // ------------------------------------------------------------ ajustes
  function renderPanel() {
    if (!ai) return;
    const gpu = (ai.providers || []).find((x) => x !== 'CPUExecutionProvider');
    const rt = ai.runtime
      ? '<div class="notice ok">' + iconHTML('check') + '<div><b>Motor de IA instalado.</b> ' + (gpu === 'DmlExecutionProvider' ? 'Aceleración por GPU con DirectML (tu Radeon).' : gpu ? 'Aceleración por GPU: ' + VL.esc(gpu) + '.' : 'Funcionando con la CPU.') + '</div></div>'
      : '<div class="notice warn">' + iconHTML('alert') + '<div><b>El motor de IA no está instalado.</b> Se instalan ONNX Runtime' + (VL.S.app.platform === 'win32' ? ' con DirectML' : '') + ' y tokenizers (~60 MB). <button class="link" id="ai-rt">Instalar ahora</button></div></div>';
    $('#ai-panel').innerHTML = rt + '<div class="models">' + ai.models.filter((m) => m.task !== 'vc_live').map((m) =>
      '<div class="model-row"><div class="grow"><b>' + VL.esc(m.name) + '</b><div class="small muted">' + (m.task === 'tts' ? 'Texto a voz y clonación instantánea' : 'Conversión de voz en tiempo real') + ' · ~' + gb(m.approx_gb) + ' GB · Licencia: ' + VL.esc(m.license) + ' · ' + VL.esc(m.repo) + '</div></div>' +
      (m.deprecated ? '<button class="btn sm" data-ai-del="' + m.id + '">Eliminar (libera ' + gb(m.approx_gb) + ' GB)</button>'
        : m.installed ? '<span class="badge" style="background:var(--ok-soft);color:var(--ok)">Instalado</span><button class="btn sm ghost" data-ai-del="' + m.id + '">Eliminar</button>'
        : '<button class="btn sm" data-ai-get="' + m.id + '"' + (ai.runtime ? '' : ' disabled title="Instala primero el motor de IA"') + '>' + iconHTML('download') + 'Descargar</button>') + '</div>').join('') + '</div>' +
      '<div class="field-hint" style="margin-top:10px">Sin cuotas ni API de pago. La descarga se verifica con SHA-256 y se puede reanudar si se corta.</div>' +
      devicesHTML() + livePanelHTML();
    const dt = $('#dev-tts'), dr = $('#dev-rvc');
    if (dt) dt.onchange = async () => VL.applyResponse(await VL.call('update_settings', { ai: { tts_device: dt.value } }));
    if (dr) dr.onchange = async () => VL.applyResponse(await VL.call('update_settings', { ai: { rvc_device: dr.value } }));
    const li = $('#live-install');
    if (li) li.onclick = installLive;
    const lr = $('#live-remove');
    if (lr) lr.onclick = async () => {
      if (!window.confirm('¿Eliminar la voz instantánea en directo (PyTorch y sus modelos)? Podrás volver a instalarla.')) return;
      const r = await VL.call('ai_remove_live'); if (r.ok) { ai = r.ai; renderPanel(); voiceSig = ''; renderVoice(); }
    };
    const b = $('#ai-rt');
    if (b) b.onclick = async () => { if (await job(await VL.call('ai_install_runtime'))) { VL.toast('ok', 'Motor de IA instalado. Reinicia VoiceLab AI si no aparece la GPU.'); refresh(); } };
    $$('[data-ai-get]').forEach((el) => el.onclick = async () => {
      if (await job(await VL.call('ai_install_model', el.dataset.aiGet))) { VL.toast('ok', 'Modelo descargado e instalado.'); refresh(); }
    });
    $$('[data-ai-del]').forEach((el) => el.onclick = async () => {
      if (!window.confirm('¿Eliminar este modelo del disco? Podrás volver a descargarlo.')) return;
      const r = await VL.call('ai_remove_model', el.dataset.aiDel); if (r.ok) { ai = r.ai; renderPanel(); renderTTS(); }
    });
  }

  // ---------------------------------------------- CPU o GPU por motor
  function devicesHTML() {
    const set = VL.S.settings.ai;
    const opt = (v, cur, t) => '<option value="' + v + '"' + (v === cur ? ' selected' : '') + '>' + t + '</option>';
    return '<div class="divider"></div><div class="grid cols-2" style="gap:14px">' +
      '<div class="field"><div class="field-label">Texto a voz se ejecuta en</div><select id="dev-tts">' +
        opt('cpu', set.tts_device, 'CPU (recomendado, más fiable)') + opt('gpu', set.tts_device, 'GPU con DirectML (experimental)') + '</select>' +
        '<div class="field-hint">Si la GPU falla, la app repite con la CPU automáticamente.</div></div>' +
      '<div class="field"><div class="field-label">Voces RVC en directo se ejecutan en</div><select id="dev-rvc">' +
        opt('gpu', set.rvc_device, 'GPU con DirectML') + opt('cpu', set.rvc_device, 'CPU') + '</select>' +
        '<div class="field-hint">Todos los modelos se cargan en un proceso aparte: la ventana no se congela.</div></div></div>';
  }

  // ------------------------------------- voz instantánea en directo
  function benchText(bn) {
    if (!bn) return '';
    const load = Math.round(bn.rtf * 100);
    return 'Prueba en este equipo: ' + bn.ms_per_chunk + ' ms de cálculo por cada bloque de ' + Math.round(bn.chunk_ms) + ' ms (' + load + ' % de un núcleo)' +
      (bn.rtf > 0.8 ? ' — va muy justo, puede entrecortarse.' : '.');
  }

  function livePanelHTML() {
    const lv = ai.live;
    if (!lv) return '';
    const badge = '<span class="badge" style="background:var(--warn-soft);color:var(--warn)">Experimental</span>';
    return '<div class="divider"></div><div class="model-row"><div class="grow"><b>Voz instantánea en directo</b> ' + badge +
      '<div class="small muted">Habla en tiempo real con cualquier voz clonada de unos 30 s, sin entrenar (MeanVC2, conversión «zero-shot»). Solo CPU. ' +
      'Descarga ~' + gb(lv.download_gb) + ' GB (PyTorch para CPU desde PyPI y modelos desde Hugging Face), ~' + gb(lv.disk_gb) + ' GB en disco. Licencia: ' + VL.esc(lv.license) + '.</div>' +
      (lv.installed && lv.bench ? '<div class="small" style="margin-top:4px">' + VL.esc(benchText(lv.bench)) + '</div>' : '') +
      (!lv.installed && (lv.runtime || lv.weights) ? '<div class="small muted" style="margin-top:4px">Instalación incompleta: pulsa «Instalar» para terminarla.</div>' : '') +
      '</div>' +
      (lv.installed ? '<span class="badge" style="background:var(--ok-soft);color:var(--ok)">Instalado</span><button class="btn sm ghost" id="live-remove">Eliminar</button>'
        : lv.supported ? '<button class="btn sm" id="live-install">' + iconHTML('download') + 'Instalar</button>'
          : '<span class="small muted" style="max-width:220px">Necesita la instalación estándar («Instalar VoiceLab AI.bat»).</span>') + '</div>';
  }

  async function installLive() {
    const lv = ai.live;
    const msg = 'Se descargarán unos ' + gb(lv.download_gb) + ' GB:\n\n' +
      '• PyTorch 2.5.1 para CPU y sus dependencias (PyPI), en un entorno aparte dentro de la carpeta de VoiceLab AI.\n' +
      '• Modelos MeanVC2 de ASLP-lab (Hugging Face, Apache 2.0).\n' +
      '• Codificador de hablante WavLM-Large/ECAPA de Microsoft UniSpeech (1,3 GB, réplica en Hugging Face, SHA-256 verificado).\n\n' +
      'Es gratuito y después funciona sin Internet. Al terminar se hace una prueba de velocidad en tu CPU. ¿Continuar?';
    if (!window.confirm(msg)) return;
    const res = await job(await VL.call('ai_install_live'));
    if (res && res.installed) {
      VL.toast('ok', 'Voz instantánea en directo instalada. ' + benchText(res.hd && res.bench_hd ? res.bench_hd : res.bench));
      if (res.hd_error) VL.toast('info', 'La alta definición no se pudo descargar ahora (' + res.hd_error + '). Puedes reintentarlo desde el modulador.');
      voiceSig = ''; refresh();
    }
  }

  // --------------------------------------------------------- texto a voz
  function ttsReady() { return ai && ai.runtime && ai.models.some((m) => m.task === 'tts' && m.installed && !m.deprecated); }

  function renderTTS() {
    if (!ai) return;
    const voices = profiles.filter((p) => p.has_reference);
    const sel = $('#tts-voice'), cur = sel.value;
    sel.innerHTML = voices.length ? voices.map((p) => '<option value="' + p.id + '">' + VL.esc(p.name) + '</option>').join('') : '<option value="">No hay voces clonadas todavía</option>';
    if (cur) sel.value = cur;
    const lang = $('#tts-lang');
    if (!lang.options.length) lang.innerHTML = Object.entries(ai.languages).map(([k, v]) => '<option value="' + k + '">' + VL.esc(v) + '</option>').join('');
    let note = '';
    if (!ttsReady()) note = '<div class="notice warn" style="margin-bottom:12px">' + iconHTML('alert') + '<div>Para generar voz necesitas el motor de IA y el modelo Chatterbox. <button class="link" data-goto="settings">Instálalos en Ajustes</button>.</div></div>';
    else if (!voices.length) note = '<div class="notice info" style="margin-bottom:12px">' + iconHTML('info') + '<div>Crea primero una voz en <button class="link" data-goto="clone">Clonar voz</button> o graba la tuya en <button class="link" data-goto="create">Crear voz</button>.</div></div>';
    $('#tts-engine-note').innerHTML = note;
    $('#tts-go').disabled = !ttsReady() || !voices.length;
    if (ttsReady() && VL.S.page === 'tts') { VL.call('tts_preload'); watchTTS(); }
  }

  // Estado del motor (se carga en segundo plano al abrir la página).
  let ttsTimer = null;
  function watchTTS() {
    if (ttsTimer) return;
    const tick = async () => {
      const r = await VL.call('tts_status');
      const el = $('#tts-engine-state');
      if (!r.ok || !el) return;
      const t = r.tts;
      el.innerHTML = t.state === 'loading' ? '<span class="spin-dot"></span> Preparando el motor… ' + VL.esc(t.stage || '') + ' <span class="muted">(tarda 1–3 minutos cada vez que abres la app; después cada frase sale en segundos. Puedes ir escribiendo)</span>'
        : t.state === 'ready' ? '● Motor listo' + (t.device === 'gpu' ? ' (GPU)' : ' (CPU)')
        : t.state === 'error' ? 'No se pudo preparar el motor: ' + VL.esc(t.error || '') : '';
      if (VL.S.page !== 'tts' || t.state === 'ready' || t.state === 'error') { clearInterval(ttsTimer); ttsTimer = null; }
    };
    ttsTimer = setInterval(tick, 1000);
    tick();
  }

  async function renderTTSList() {
    const r = await VL.call('list_items');
    const items = (r.items || []).filter((i) => i.kind === 'tts');
    $('#tts-list').innerHTML = items.length ? items.map((i) =>
      '<div class="rec-row"><div class="grow"><b>' + VL.esc(i.name) + '</b> <span class="small muted num">' + i.duration.toFixed(1) + ' s</span></div>' +
      '<button class="btn sm" data-tts-play="' + i.id + '">' + iconHTML('play') + 'Escuchar</button>' +
      '<select data-tts-fmt="' + i.id + '" style="width:auto"><option>wav</option><option>mp3</option><option>flac</option><option>ogg</option></select>' +
      '<button class="btn sm" data-tts-dl="' + i.id + '">' + iconHTML('download') + 'Descargar</button>' +
      '<button class="btn sm ghost" data-tts-edit="' + i.id + '">Editar</button></div>').join('')
      : '<div class="small muted">Aquí aparecerán los audios que generes.</div>';
  }

  async function generate() {
    const val = (k) => parseFloat($('[data-tts="' + k + '"] input[type=number]').value);
    $('#tts-cancel').hidden = false; $('#tts-go').disabled = true;
    const res = await job(await VL.call('tts_generate', {
      profile_id: $('#tts-voice').value, text: $('#tts-text').value, language: $('#tts-lang').value,
      speed: val('speed'), stability: val('stability') / 100, expressivity: val('expressivity') / 100 }));
    $('#tts-cancel').hidden = true; $('#tts-go').disabled = false;
    if (res && res.id) {
      VL.toast('ok', 'Audio generado (' + res.duration.toFixed(1) + ' s' + (res.device === 'gpu' ? ', con la GPU' : ', con la CPU') + ').');
      if (res.fallback) VL.toast('info', 'La GPU falló y se usó la CPU; queda seleccionada la CPU en Ajustes. Detalle: ' + res.fallback);
      renderTTSList(); VL.call('play_item', res.id);
    }
  }

  // ---------------------------------------------------- voz en el modulador
  // La estructura se reconstruye solo cuando cambia algo relevante; el estado
  // (latencia, cortes…) se actualiza aparte para no romper los controles.
  let voiceSig = '';
  function renderVoice() {
    const box = $('#ai-voice');
    if (!box || !VL.S.settings) return;
    const set = VL.S.settings;
    const prof = profiles.find((p) => p.id === set.voice.profile_id);
    const live = ai && ai.live;
    const sig = JSON.stringify([prof && prof.id, prof && prof.type, prof && prof.has_reference, live && live.installed,
      set.voice.instant_live, set.ai.meanvc_variant, set.voice.rvc_pitch, set.voice.ai_polish, set.voice.ai_clean_input,
      set.ai.meanvc_hd, live && live.hd]);
    if (sig !== voiceSig) { voiceSig = sig; buildVoice(box, prof, live); if (prof && prof.type === 'instant') box.insertAdjacentHTML('beforeend', '<div id="train-box" style="margin-top:14px"></div>'); }
    renderVoiceStatus(prof);
    if (prof && prof.type === 'instant') trainTick(prof);
  }

  // ------------------------------------------------ entrenar una voz fiel
  let trainInfo = null, trainFor = null, trainAt = 0, trainBusy = false, trainWas = '';
  const TRAIN_ACTIVE = ['starting', 'preparing', 'training', 'finishing'];
  function fmtEta(s) {
    s = Math.max(0, Math.round(s || 0));
    const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return h ? h + ' h ' + m + ' min' : m + ' min';
  }
  async function trainTick(prof, force) {
    const active = trainInfo && TRAIN_ACTIVE.includes((trainInfo.status || {}).state);
    if (!force && trainFor === prof.id && Date.now() - trainAt < (active ? 2000 : 20000)) { paintTrain(prof); return; }
    if (trainBusy) return;
    trainBusy = true; trainAt = Date.now();
    try {
      const r = await VL.call('rvc_train_info', prof.id);
      if (r.ok) { trainInfo = r.train; trainFor = prof.id; }
    } finally { trainBusy = false; }
    const st = (trainInfo && trainInfo.status) || {};
    if (trainWas && TRAIN_ACTIVE.includes(trainWas) && st.state === 'done') {
      VL.toast('ok', 'Voz fiel lista. Pulsa «Usar la voz fiel» para hablar con ella en directo.');
      refresh();
    }
    trainWas = st.state || '';
    paintTrain(prof);
  }
  function paintTrain(prof) {
    const el = $('#train-box');
    if (!el || !trainInfo || trainFor !== prof.id) return;
    const t = trainInfo, st = t.status || {};
    const active = TRAIN_ACTIVE.includes(st.state);
    let html;
    if (active && st.profile_id === prof.id) {
      const pct = Math.round((st.progress || 0) * 100);
      html = '<div class="notice info">' + iconHTML('sparkles') + '<div style="flex:1"><b>Entrenando la voz fiel</b> · ' + pct + ' %' +
        (st.eta_s ? ' · quedan ≈ ' + fmtEta(st.eta_s) : '') +
        '<div class="progress" style="margin:8px 0"><i style="width:' + pct + '%"></i></div>' +
        '<div class="small muted">' + VL.esc(st.phase || '') + (st.data_minutes ? ' · ' + st.data_minutes + ' min de voz' : '') + '</div>' +
        '<div class="small muted" style="margin-top:4px">Puedes seguir usando el PC (va con prioridad baja). Si cierras la app, se guarda y luego puedes continuar.</div>' +
        '<button class="btn sm" id="train-stop" style="margin-top:8px">Parar y usar lo aprendido</button></div></div>';
    } else if (active) {
      html = '<div class="notice info">' + iconHTML('info') + '<div>Se está entrenando «' + VL.esc(st.name || '') + '». Cuando termine podrás entrenar esta.</div></div>';
    } else if (!t.material || t.speech_s < t.min_s) {
      html = '<div class="notice info">' + iconHTML('info') + '<div><b>¿Quieres que suene mucho más fiel?</b> Se puede entrenar un modelo con esta voz, pero hace falta al menos 1 minuto de voz (mejor 10 min o más)' +
        (t.speech_s ? ': este perfil tiene ' + t.speech_s + ' s' : '') + '. Crea el perfil en «Clonar voz» con un audio más largo.</div></div>';
    } else {
      const mins = Math.round(t.speech_s / 60);
      const opts = Object.entries(t.durations).map(([k, v]) => '<option value="' + k + '"' + (k === '120' ? ' selected' : '') + '>' + VL.esc(v) + '</option>').join('');
      html = '<div class="card" style="padding:14px"><div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">' + iconHTML('sparkles') + '<b>Voz fiel (entrenada)</b></div>' +
        '<div class="small muted">Entrena con tus ' + mins + ' min de voz un modelo RVC mucho más parecido que la voz instantánea, para hablar en directo con ~0,15–0,2 s de retraso (con la GPU). ' +
        'Se hace una vez, en tu PC, con prioridad baja; puedes pararlo cuando quieras y se queda lo aprendido.' + (t.speech_s < t.good_s ? ' Con más audio (10 min o más) queda aún más fiel.' : '') + '</div>' +
        (st.state === 'error' ? '<div class="notice warn" style="margin-top:8px">' + iconHTML('alert') + '<div>' + VL.esc(st.error || st.phase || '') + '</div></div>' : '') +
        '<div style="display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap"><select id="train-min">' + opts + '</select>' +
        (t.trained_profile
          ? '<button class="btn sm primary" id="train-use">Usar la voz fiel</button><button class="btn sm" id="train-more">Seguir entrenando</button>'
          : '<button class="btn sm primary" id="train-go">' + (t.checkpoint ? 'Continuar el entrenamiento' : 'Entrenar voz fiel') + '</button>') +
        '</div></div>';
    }
    if (el.dataset.html === html) return;
    el.dataset.html = html; el.innerHTML = html;
    const go = async (extend) => {
      const minutes = parseFloat(($('#train-min') || {}).value || '120');
      const r = await VL.call('rvc_train_start', prof.id, minutes, !!extend);
      if (!r.ok) { VL.toast('err', r.error); return; }
      trainInfo.status = r.status; trainWas = r.status.state; paintTrain(prof); trainTick(prof, true);
    };
    const b1 = $('#train-go'); if (b1) b1.onclick = () => go(false);
    const b2 = $('#train-more'); if (b2) b2.onclick = () => go(true);
    const b3 = $('#train-use'); if (b3) b3.onclick = async () => VL.applyResponse(await VL.call('activate_profile', t.trained_profile));
    const b4 = $('#train-stop'); if (b4) b4.onclick = async () => { b4.disabled = true; const r = await VL.call('rvc_train_stop'); if (r.ok) { trainInfo.status = r.status; paintTrain(prof); } };
  }

  // Acabado de estudio: limpieza antes de la IA y producción (de-esser, compresión, nivel) después.
  function qualityHTML() {
    const v = VL.S.settings.voice;
    return '<div class="fx-row" style="margin-top:10px;gap:18px;display:flex;flex-wrap:wrap">' +
      '<label class="checkbox" title="Paso alto y reducción de ruido suave: el modelo entiende mejor tu voz"><input type="checkbox" id="q-clean"' + (v.ai_clean_input ? ' checked' : '') + '><span>Limpiar mi voz antes de convertir</span></label>' +
      '<label class="checkbox" title="Control de eses, compresión suave, presencia y volumen constante, como en una voz producida"><input type="checkbox" id="q-polish"' + (v.ai_polish ? ' checked' : '') + '><span>Acabado de estudio</span></label></div>';
  }

  function bindQuality() {
    const c = $('#q-clean'), q = $('#q-polish');
    if (c) c.onchange = async () => VL.applyResponse(await VL.call('update_settings', { voice: { ai_clean_input: c.checked } }));
    if (q) q.onchange = async () => VL.applyResponse(await VL.call('update_settings', { voice: { ai_polish: q.checked } }));
  }

  function buildVoice(box, prof, live) {
    const set = VL.S.settings;
    if (!prof || prof.type === 'effects') { box.innerHTML = ''; return; }
    if (prof.type === 'instant') {
      if (!live || !live.installed) {
        const can = live && live.supported;
        box.innerHTML = '<div class="notice info">' + iconHTML('info') + '<div>«' + VL.esc(prof.name) + '» es una voz de IA instantánea: ya puedes usarla en <b>Texto a voz</b>. ' +
          'Para <b>hablar con ella en directo</b> (sin entrenar nada) falta un componente que se instala una sola vez: ~' + gb(live ? live.download_gb : 1.9) + ' GB, gratis.' +
          (can ? ' <button class="btn sm primary" id="live-install-here" style="margin-top:8px">' + iconHTML('download') + 'Instalar la voz en directo</button>' : '') + '</div></div>';
        const bi = $('#live-install-here');
        if (bi) bi.onclick = installLive;
        return;
      }
      if (!prof.has_reference) {
        box.innerHTML = '<div class="notice warn">' + iconHTML('alert') + '<div>Este perfil no tiene audio de referencia. Vuelve a crearlo en «Clonar voz».</div></div>';
        return;
      }
      box.innerHTML =
        '<label class="checkbox" style="font-size:13.5px;color:var(--text)"><input type="checkbox" id="live-on"' + (set.voice.instant_live ? ' checked' : '') + '>' +
        '<span><b>Hablar en directo con esta voz</b> <span class="badge" style="background:var(--warn-soft);color:var(--warn)">Experimental</span></span></label>' +
        '<div class="fx-row" style="margin-top:10px"><div class="field-label">Modo</div><select id="live-variant">' +
        Object.entries(live.variants).map(([k, v]) => '<option value="' + k + '"' + (k === set.ai.meanvc_variant ? ' selected' : '') + '>' + VL.esc(v) + '</option>').join('') +
        '</select></div>' + qualityHTML() +
        (set.ai.meanvc_variant !== '120ms'
          ? ''
          : live.hd ? '<label class="checkbox" style="margin-top:8px" title="AP-BWE reconstruye los agudos (de 16 kHz a 48 kHz). Usa bastante más CPU y añade ~25 ms; la mejora es pequeña."><input type="checkbox" id="q-hd"' + (set.ai.meanvc_hd ? ' checked' : '') + '><span>Alta definición 48 kHz</span></label>' +
          (live.bench_hd ? '<div class="small muted">' + VL.esc(benchText(live.bench_hd)) + (live.bench_hd.rtf >= 0.85 ? ' Se usa la calidad normal para no entrecortar.' : '') + '</div>' : '')
          : '<div class="small muted" style="margin-top:8px">Alta definición 48 kHz (algo más de nitidez, más CPU): <button class="link" id="q-hd-get">descargar ' + live.hd_mb + ' MB</button></div>') +
        '<div class="notice info" style="margin-top:10px">' + iconHTML('info') + '<div><b>¿Suena robótica en Discord?</b> En Discord → Ajustes → Voz y vídeo, con «CABLE Output» como micrófono: ' +
          'pon <b>Supresión de ruido</b> en «Ninguna» y desactiva <b>Cancelación de eco</b>, <b>Control automático de ganancia</b> y el <b>procesamiento de voz avanzado</b>. ' +
          'Esos filtros están pensados para voces reales y deforman la voz convertida.</div></div>' +
        '<div id="live-status" style="margin-top:10px"></div>' +
        '<div class="field-hint" style="margin-top:8px">Conversión sin entrenamiento a partir de la referencia del perfil. Se parece menos que una voz RVC entrenada y el modelo se entrenó sobre todo con inglés y chino: en español la pronunciación puede sonar menos natural. La primera vez con cada voz tarda unos segundos más (calcula su huella).</div>';
      $('#live-on').onchange = async (e) => VL.applyResponse(await VL.call('update_settings', { voice: { instant_live: e.target.checked } }));
      $('#live-variant').onchange = async (e) => VL.applyResponse(await VL.call('update_settings', { ai: { meanvc_variant: e.target.value } }));
      bindQuality();
      const hdc = $('#q-hd');
      if (hdc) hdc.onchange = async () => VL.applyResponse(await VL.call('update_settings', { ai: { meanvc_hd: hdc.checked } }));
      const hdg = $('#q-hd-get');
      if (hdg) hdg.onclick = async () => {
        const r = await job(await VL.call('ai_install_hd'));
        if (r && r.hd) { VL.toast('ok', 'Alta definición lista. ' + benchText(r.bench_hd)); await refresh(); voiceSig = ''; renderVoice();
          VL.applyResponse(await VL.call('activate_profile', VL.S.settings.voice.profile_id)); }
      };
      return;
    }
    const pitch = set.voice.rvc_pitch;
    box.innerHTML = '<div id="live-status"></div>' +
      '<div class="fx-row" style="margin-top:10px"><div class="field-label">Ajuste de tono para esta voz</div><div class="range-field" id="rvc-pitch"><input type="range" min="-24" max="24" step="1" value="' + pitch + '"><input type="number" min="-24" max="24" step="1" value="' + pitch + '"><span class="unit">st</span></div></div>' +
      qualityHTML();
    bindQuality();
    box.querySelectorAll('#rvc-pitch input').forEach((i) => i.onchange = async () => {
      VL.applyResponse(await VL.call('update_settings', { voice: { rvc_pitch: parseFloat(i.value) } }));
    });
  }

  function renderVoiceStatus(prof) {
    const el = $('#live-status');
    if (!el || !prof) return;
    const status = VL.S.status || {};
    const st = status.ai;
    const instant = prof.type === 'instant';
    let html;
    if (instant && !VL.S.settings.voice.instant_live) html = '';
    else if (st && st.error) {
      html = '<div class="notice warn">' + iconHTML('alert') + '<div><b>La conversión se ha detenido.</b> ' + VL.esc(st.error) + ' <button class="link" id="live-retry">Reintentar</button></div></div>';
    } else if (st) {
      html = '<div class="notice ok">' + iconHTML('check') + '<div><b>' + (instant ? 'Voz instantánea en directo activa.' : 'Conversión por IA activa.') + '</b> ' +
        'Cálculo ' + st.infer_ms + ' ms por bloque de ' + st.block_ms + ' ms · latencia añadida ≈ ' + Math.round(st.latency_ms) + ' ms' +
        (st.underruns ? ' · ' + st.underruns + ' cortes' : '') + '</div></div>' +
        ((st.dropped_ms || (st.block_ms && st.infer_ms > 0.85 * st.block_ms))
          ? '<div class="notice warn" style="margin-top:8px">' + iconHTML('alert') + '<div><b>El procesador no llega a tiempo</b>' + (st.dropped_ms ? ' (' + st.dropped_ms + ' ms descartados)' : '') +
            ': la voz se entrecorta y suena robótica. ' + (VL.S.settings.ai.meanvc_variant === '40ms' ? 'Cambia el modo a <b>«Calidad»</b> (gasta 3 veces menos) o cierra programas pesados.' : 'Desactiva la alta definición o cierra programas pesados.') + '</div></div>'
          : '');
    } else {
      html = '<div class="notice info">' + iconHTML('info') + '<div>' + (status.running ? 'Cargando la voz…' : 'La conversión se activa al encender el modulador.') + '</div></div>';
    }
    if (el.dataset.html !== html) {
      el.dataset.html = html; el.innerHTML = html;
      const r = $('#live-retry');
      if (r) r.onclick = async () => VL.applyResponse(await VL.call('activate_profile', prof.id));
    }
  }

  function init() {
    VL = window.VL; $ = VL.$; $$ = VL.$$;
    $('#tts-text').addEventListener('input', () => { $('#tts-count').textContent = $('#tts-text').value.length + ' caracteres'; });
    $$('[data-tts]').forEach((el) => {
      const [r, n] = el.querySelectorAll('input');
      const paint = () => r.style.setProperty('--pct', ((r.value - r.min) / (r.max - r.min) * 100) + '%');
      r.addEventListener('input', () => { n.value = r.value; paint(); });
      n.addEventListener('change', () => { r.value = n.value; paint(); });
      paint();
    });
    $('#tts-go').addEventListener('click', generate);
    $('#tts-cancel').addEventListener('click', () => VL.call('tts_cancel'));
    $('#tts-list').addEventListener('click', async (e) => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.ttsPlay) VL.call('play_item', b.dataset.ttsPlay);
      if (b.dataset.ttsEdit) window.VLStudio.openEditor(b.dataset.ttsEdit);
      if (b.dataset.ttsDl) {
        const res = await job(await VL.call('export_item', b.dataset.ttsDl, $('[data-tts-fmt="' + b.dataset.ttsDl + '"]').value));
        if (res && res.path) { VL.toast('ok', 'Guardado: ' + res.path); if (VL.S.app.platform === 'win32') VL.call('reveal_path', res.path); }
      }
    });
    const importRvc = async (name, b64, filename) => {
      const r = await VL.call('import_rvc_model', name, b64 || null, filename || null);
      if (r.needs_upload) { $('#rvc-file').click(); return; }
      const res = await job(r);
      if (res && res.id) { VL.toast('ok', 'Modelo RVC importado como «' + res.name + '» (' + Math.round(res.model.sr / 1000) + ' kHz).'); document.dispatchEvent(new CustomEvent('vl:profiles')); }
    };
    $('#lib-import-rvc').addEventListener('click', () => {
      if (!(ai && ai.runtime && ai.models.some((m) => m.id === 'rvc-base' && m.installed))) {
        VL.toast('err', 'Antes instala el motor de IA y la «Base para conversión RVC» en Ajustes → Motor de IA.'); return;
      }
      importRvc(window.prompt('Nombre para la voz RVC:', 'Mi voz RVC') || 'Voz RVC');
    });
    $('#rvc-file').addEventListener('change', () => {
      const f = $('#rvc-file').files[0]; if (!f) return;
      const rd = new FileReader();
      rd.onload = () => importRvc(f.name.replace(/\.onnx$/i, ''), rd.result, f.name);
      rd.readAsDataURL(f); $('#rvc-file').value = '';
    });
    document.addEventListener('vl:page', (e) => { if (['settings', 'tts', 'modulator'].includes(e.detail)) refresh(); if (e.detail === 'tts') renderTTSList(); });
    document.addEventListener('vl:profiles', refresh);
    document.addEventListener('vl:settings', renderVoice);
    $('#upd-url').value = VL.S.settings.ui.updates_url || '';
    $('#upd-url').addEventListener('change', async (e) => VL.applyResponse(await VL.call('update_settings', { ui: { updates_url: e.target.value.trim() } })));
    $('#upd-check').addEventListener('click', async () => {
      const r = await VL.call('check_updates');
      if (!r.ok) { VL.toast('err', r.error); return; }
      VL.toast(r.newer ? 'ok' : 'info', r.newer ? 'Hay una versión nueva: ' + r.latest + (r.url ? ' (' + r.url + ')' : '') : 'Tienes la última versión (' + r.current + ').');
    });
    setInterval(() => { if (VL.S.page === 'modulator') renderVoice(); }, 1000);
    refresh();
  }

  document.addEventListener('vl:ready', init);
})();
