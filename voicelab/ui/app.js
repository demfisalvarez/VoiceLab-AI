/* VoiceLab AI — lógica de la interfaz. */
(function () {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const call = (...a) => window.Bridge.call(...a);

  const S = {
    app: null, settings: null, devices: null, status: null, system: null,
    page: 'home', busy: false, sawSignal: false,
    lastError: null, lastRouteErrors: {}, history: [],
  };

  // ================================================================ utilidades
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function fmtDb(v, digits = 1) {
    if (v == null || v <= -119) return '−∞';
    const s = Math.abs(v).toFixed(digits);
    return (v > 0.05 ? '+' : v < -0.05 ? '−' : '') + s;
  }
  function fmtMs(v) { return v == null ? '—' : Math.round(v) + ' ms'; }
  function getPath(path) {
    const [sec, key] = path.split('.');
    return S.settings && S.settings[sec] ? S.settings[sec][key] : undefined;
  }
  function patchFor(path, value) {
    const [sec, key] = path.split('.');
    return { [sec]: { [key]: value } };
  }

  function toast(kind, text, timeout) {
    const box = document.createElement('div');
    box.className = 'toast ' + kind;
    box.innerHTML = iconHTML(kind === 'err' ? 'alert' : kind === 'ok' ? 'check' : 'info') +
      '<div>' + esc(text) + '</div><button class="x" aria-label="Cerrar">' + iconHTML('x') + '</button>';
    $('#toasts').appendChild(box);
    const close = () => box.remove();
    box.querySelector('.x').addEventListener('click', close);
    setTimeout(close, timeout || (kind === 'err' ? 9000 : 5000));
    while ($('#toasts').children.length > 4) $('#toasts').firstChild.remove();
  }

  // ================================================================ navegación
  const PAGES = ['home', 'modulator', 'library', 'clone', 'create', 'tts', 'editor', 'settings'];

  function showPage(page, persist = true) {
    if (!PAGES.includes(page)) page = 'home';
    S.page = page;
    $$('.page').forEach((p) => p.classList.toggle('active', p.id === 'page-' + page));
    $$('.nav-item').forEach((n) => n.classList.toggle('active', n.dataset.page === page));
    const sec = $('#page-' + page);
    $('#page-title').textContent = sec.dataset.title;
    $('#page-subtitle').textContent = sec.dataset.subtitle || '';
    $('#content').scrollTop = 0;
    document.dispatchEvent(new CustomEvent('vl:page', { detail: page }));
    if (persist && S.settings && S.settings.ui.last_page !== page) sendSetting('ui.last_page', page, { quiet: true });
  }

  // ============================================== páginas de fases posteriores
  const SOON = {
    library: {
      icon: 'library', phase: 6,
      title: 'Tu colección de voces, organizada',
      text: 'Guardarás aquí todos los perfiles: voces clonadas, voces creadas con tu micrófono y perfiles de efectos.',
      items: ['Carpetas, búsqueda y favoritos', 'Nombre, avatar, descripción y fecha de cada perfil', 'Audio original de referencia y ajustes de clonación', 'Duplicar, renombrar, editar y eliminar', 'Exportar e importar perfiles con sus modelos', 'Copias de seguridad locales'],
      tech: [['Almacenamiento local', '%APPDATA%\\VoiceLabAI'], ['Formato de perfil', 'Carpeta + JSON + modelos ONNX'], ['Tipos de perfil', 'Efectos · IA instantánea · IA entrenada']],
    },
    clone: {
      icon: 'voice', phase: 3,
      title: 'Clonación de voz con IA local',
      text: 'Arrastra un audio o vídeo, elige el fragmento y VoiceLab AI creará un perfil de voz que conserve timbre, acento y forma de hablar.',
      items: ['MP3, WAV, FLAC, M4A, AAC, OGG, MP4, MKV, MOV y WEBM', 'Extracción automática del audio de los vídeos', 'Selección del fragmento sobre la forma de onda', 'Separación de la voz y el ruido de fondo', 'Indicador de si hay material suficiente para una buena clonación', 'Confirmación de autorización cuando la voz no es tuya'],
      tech: [['Clonación instantánea (≈10 s)', 'Chatterbox Multilingual · MIT'], ['Modelo entrenado (10–30 min)', 'RVC v2 · MIT'], ['Aceleración', 'ONNX Runtime + DirectML (RX 6600)'], ['Limpieza', 'DeepFilterNet3 · separación MDX']],
    },
    create: {
      icon: 'record', phase: 3,
      title: 'Estudio de grabación integrado',
      text: 'Graba tu propia voz para crear perfiles nuevos o para entrenar un modelo de IA con ella.',
      items: ['Grabar, detener y escuchar', 'Recortar fragmentos', 'Eliminar ruido y normalizar volumen', 'Guardar grabaciones y usarlas para crear perfiles', 'Guardar tu voz modificada con efectos como perfil independiente (desde la Fase 2)'],
      tech: [['Captura', 'WASAPI, el mismo micrófono del modulador'], ['Formato interno', 'WAV 48 kHz, 32 bits'], ['Reducción de ruido', 'DeepFilterNet3 (local)']],
    },
    tts: {
      icon: 'tts', phase: 5,
      title: 'Texto a voz con tus voces',
      text: 'Escribe cualquier texto y genera audio con cualquiera de tus perfiles, sin cuotas ni conexión a Internet.',
      items: ['Cuadro de texto amplio para textos largos', 'Selector de voz e idioma (23 idiomas, incluido español de España)', 'Velocidad, estabilidad, expresividad y similitud', 'Historial de generaciones', 'Exportar a WAV, MP3, FLAC y OGG'],
      tech: [['Motor', 'Chatterbox Multilingual · MIT'], ['Ejecución', 'ONNX Runtime + DirectML o CPU'], ['Marca de agua', 'PerTh inaudible en cada audio generado']],
    },
    editor: {
      icon: 'editor', phase: 6,
      title: 'Editor de audio',
      text: 'Un editor sencillo pero completo para preparar muestras de voz y retocar tus generaciones.',
      items: ['Importar archivos y ver la forma de onda', 'Recortar, dividir y unir', 'Ajustar volumen, normalizar y eliminar silencios', 'Aplicar los mismos efectos del modulador', 'Exportar', 'Archivos largos procesados en segundo plano sin bloquear la interfaz'],
      tech: [['Procesado', 'NumPy/SciPy en un proceso aparte'], ['Formatos', 'WAV, FLAC, MP3, OGG (vía FFmpeg LGPL)']],
    },
  };

  function renderSoonPages() {
    $$('.soon-page').forEach((sec) => {
      const d = SOON[sec.dataset.soon];
      sec.innerHTML =
        '<div class="soon">' +
          '<div class="card soon-hero span-2">' +
            '<div class="icon-box">' + iconHTML(d.icon, 'xl') + '</div>' +
            '<span class="badge">Llega en la Fase ' + d.phase + '</span>' +
            '<h2>' + esc(d.title) + '</h2><p>' + esc(d.text) + '</p>' +
          '</div>' +
          '<div class="card"><div class="card-head"><div><h3 class="card-title">Qué incluirá</h3><div class="card-desc">Según tu especificación</div></div></div>' +
            '<ul class="bullets">' + d.items.map((x) => '<li>' + esc(x) + '</li>').join('') + '</ul></div>' +
          '<div class="card"><div class="card-head"><div><h3 class="card-title">Tecnología prevista</h3><div class="card-desc">Local, sin suscripciones</div></div></div>' +
            '<div class="tech">' + d.tech.map((t) => '<div class="tech-row"><span>' + esc(t[0]) + '</span><span>' + esc(t[1]) + '</span></div>').join('') + '</div>' +
            '<div class="notice info" style="margin-top:14px">' + iconHTML('info') + '<div>Esta sección no tiene botones todavía para no simular funciones que aún no existen.</div></div>' +
          '</div>' +
        '</div>';
    });
  }

  // ======================================================== envío de ajustes
  async function sendSetting(path, value, opts = {}) {
    const res = await call('update_settings', patchFor(path, value));
    if (res.settings) S.settings = res.settings;
    if (res.devices) S.devices = res.devices;
    if (res.status) { S.status = res.status; renderStatus(); }
    if (!res.ok) {
      toast('err', res.error || 'No se pudo guardar el ajuste.');
    }
    document.dispatchEvent(new CustomEvent('vl:settings'));
    if (!opts.quiet) {
      applySettingsToControls(opts.skip ? path : null);
      if (res.devices) renderDevices();
      renderDerived();
    }
    return res;
  }

  // ------------------------------------------------- deslizadores + número
  function setupRange(el) {
    const path = el.dataset.range;
    const min = parseFloat(el.dataset.min), max = parseFloat(el.dataset.max), step = parseFloat(el.dataset.step);
    const [range, num] = el.querySelectorAll('input');
    [range, num].forEach((i) => { i.min = min; i.max = max; i.step = step; });
    let timer = null, pending = null;
    const paint = (v) => { range.style.setProperty('--pct', ((v - min) / (max - min) * 100) + '%'); };
    const flush = () => {
      timer = null;
      if (pending == null) return;
      const v = pending; pending = null;
      sendSetting(path, v, { skip: true });
    };
    const queue = (v) => {
      pending = v;
      if (!timer) timer = setTimeout(flush, 70);
    };
    range.addEventListener('input', () => {
      const v = parseFloat(range.value);
      num.value = v;
      paint(v);
      queue(v);
    });
    num.addEventListener('change', () => {
      let v = parseFloat(num.value);
      if (isNaN(v)) v = getPath(path);
      v = Math.min(max, Math.max(min, v));
      num.value = v; range.value = v; paint(v);
      queue(v);
    });
    el._set = (v) => { range.value = v; num.value = v; paint(v); };
  }

  function setupSwitch(el) {
    el.addEventListener('click', async () => {
      const path = el.dataset.switch;
      const next = el.getAttribute('aria-checked') !== 'true';
      if (path === 'audio.monitor_enabled' && next && !(await confirmMonitor())) return;
      el.setAttribute('aria-checked', String(next));
      await sendSetting(path, next);
    });
  }

  function setupSelect(el) {
    el.addEventListener('change', () => {
      const path = el.dataset.select;
      let v = el.value;
      if (['audio.sample_rate', 'audio.block_size', 'audio.buffer_blocks'].includes(path)) v = parseInt(v, 10);
      else if (v === '') v = null;
      sendSetting(path, v);
    });
  }

  function applySettingsToControls(skipPath) {
    if (!S.settings) return;
    $$('[data-range]').forEach((el) => { if (el.dataset.range !== skipPath && el._set) el._set(getPath(el.dataset.range)); });
    $$('[data-switch]').forEach((el) => el.setAttribute('aria-checked', String(!!getPath(el.dataset.switch))));
    $$('select[data-select]').forEach((el) => {
      const v = getPath(el.dataset.select);
      const want = v == null ? '' : String(v);
      if ([...el.options].some((o) => o.value === want)) el.value = want;
    });
  }

  // =============================================================== dispositivos
  const ROUTES = [
    { key: 'cable', icon: 'plug', title: 'Micrófono virtual', desc: 'Lo que reciben Discord, Steam, juegos, navegadores y videollamadas.', label: 'Salida del cable virtual' },
    { key: 'monitor', icon: 'headphones', title: 'Monitorización', desc: 'Escucha tu voz procesada por altavoces o auriculares.', label: 'Dispositivo de escucha' },
    { key: 'aux', icon: 'phone', title: 'Salida auxiliar', desc: 'Una salida más e independiente: por ejemplo, un adaptador de audio conectado a un teléfono para llamadas.', label: 'Dispositivo' },
  ];

  function buildRoutes() {
    $('#routes').innerHTML = ROUTES.map((r) =>
      '<div class="route" data-route="' + r.key + '">' +
        '<div class="icon-box ' + (r.key === 'cable' ? 'cyan' : '') + '">' + iconHTML(r.icon) + '</div>' +
        '<div style="min-width:0">' +
          '<div class="route-title">' + esc(r.title) + ' <span class="badge" data-r="badge">Desactivada</span></div>' +
          '<div class="route-desc">' + esc(r.desc) + '</div>' +
          '<div class="route-body">' +
            '<div class="field"><div class="field-label">' + esc(r.label) + '</div><select data-select="audio.' + r.key + '_device" data-route-select="' + r.key + '"></select></div>' +
            '<div class="field"><div class="field-label">Volumen</div><div class="range-field" data-range="audio.' + r.key + '_volume_db" data-min="-60" data-max="12" data-step="0.5"><input type="range"><input type="number"><span class="unit">dB</span></div></div>' +
            (r.key === 'monitor' ? '<div class="field"><div class="field-label">Qué escuchas</div><select data-select="audio.monitor_source"><option value="processed">Mi voz con efectos</option><option value="original">Mi micrófono original (sin efectos)</option></select></div>' : '') +
            (r.key === 'cable' ? '<div class="field" style="grid-column:1/-1;display:flex;gap:12px;align-items:flex-start">' +
              '<button class="switch" role="switch" data-switch="audio.system_mic" aria-label="Usar en todas las apps" style="margin-top:2px;flex:none"></button>' +
              '<div><b>En todas las apps</b><div class="field-hint" style="margin-top:2px">Mientras el modulador está encendido, el micrófono virtual pasa a ser el <b>micrófono predeterminado de Windows</b>: juegos, editores de vídeo y cualquier programa que use el micrófono predeterminado reciben tu voz modulada sin configurar nada. Al parar el modulador vuelve tu micrófono de siempre.</div>' +
              '<div data-r="sysmic" style="margin-top:6px"></div></div></div>' : '') +
          '</div>' +
          '<div class="meter-h" data-meter="route-' + r.key + '"><div class="fill"></div><div class="peak"></div></div>' +
          '<div class="route-stats"><span>Latencia <b class="num" data-r="lat">—</b></span><span>Cortes <b class="num" data-r="under">0</b></span><span data-r="limit"></span><span style="flex:1"></span>' +
            '<button class="btn sm" data-tone="' + r.key + '">' + iconHTML('play') + 'Probar salida</button></div>' +
          '<div class="route-error" data-r="error"></div>' +
        '</div>' +
        '<button class="switch" role="switch" data-switch="audio.' + r.key + '_enabled" aria-label="Activar ' + esc(r.title) + '"></button>' +
      '</div>').join('');
  }

  function option(value, label, selected, disabled) {
    return '<option value="' + esc(value) + '"' + (selected ? ' selected' : '') + (disabled ? ' disabled' : '') + '>' + esc(label) + '</option>';
  }

  function fillSelect(sel, opts, current) {
    // opts: [{value,label,disabled,group}]
    let html = '', group = null;
    const known = opts.some((o) => o.value === (current || ''));
    if (current && !known) opts = [{ value: current, label: current + ' (no conectado)' }].concat(opts);
    for (const o of opts) {
      if (o.group !== group) {
        if (group) html += '</optgroup>';
        if (o.group) html += '<optgroup label="' + esc(o.group) + '">';
        group = o.group;
      }
      html += option(o.value, o.label, (current || '') === o.value, o.disabled);
    }
    if (group) html += '</optgroup>';
    sel.innerHTML = html;
  }

  function renderDevices() {
    const d = S.devices;
    const a = S.settings.audio;
    const errBox = $('#devices-error');
    if (!d || !d.available) {
      errBox.innerHTML = '<div class="notice err" style="margin-bottom:14px">' + iconHTML('alert') + '<div>' + esc((d && d.error) || 'El sistema de audio no está disponible.') + '</div></div>';
    } else {
      errBox.innerHTML = '';
    }
    if (!d) return;
    fillSelect($('#sel-hostapi'), d.hostapis.map((h) => ({ value: h.name, label: h.label })), d.hostapi || '');
    const defIn = d.defaults.input;
    fillSelect($('#sel-input'), [{ value: '', label: 'Predeterminado de Windows' + (defIn ? ' (' + defIn + ')' : '') }].concat(
      d.inputs.map((x) => ({ value: x.name, label: x.name + (x.kind === 'vbcable_record' ? ' — micrófono virtual, no válido como entrada' : ''), disabled: x.kind === 'vbcable_record' }))), a.input_device);

    const outs = d.outputs;
    const isCable = (x) => x.kind === 'vbcable_playback' || x.kind === 'virtual';
    fillSelect($('[data-route-select="cable"]'),
      [{ value: '', label: d.virtual.cable_output ? 'Automático (' + d.virtual.cable_output + ')' : 'Automático (no se detecta ningún cable virtual)' }]
        .concat(outs.filter(isCable).map((x) => ({ value: x.name, label: x.name, group: 'Dispositivos virtuales' })))
        .concat(outs.filter((x) => !isCable(x)).map((x) => ({ value: x.name, label: x.name, group: 'Otros dispositivos' }))),
      a.cable_device);
    const physical = outs.filter((x) => x.kind !== 'vbcable_playback');
    fillSelect($('[data-route-select="monitor"]'),
      [{ value: '', label: 'Predeterminado de Windows' + (d.defaults.monitor ? ' (' + d.defaults.monitor + ')' : '') }]
        .concat(physical.map((x) => ({ value: x.name, label: x.name }))), a.monitor_device);
    fillSelect($('[data-route-select="aux"]'),
      [{ value: '', label: 'Elige un dispositivo…' }].concat(physical.map((x) => ({ value: x.name, label: x.name }))), a.aux_device);

    // Estado del micrófono virtual
    const v = d.virtual || {};
    const st = $('#virtual-status');
    if (!d.available) {
      st.innerHTML = '';
    } else if (v.cable_output) {
      st.innerHTML = '<div class="notice ok">' + iconHTML('check') + '<div><b>' + (v.is_vbcable ? 'VB-CABLE instalado.' : 'Dispositivo virtual detectado.') + '</b> VoiceLab AI escribirá en «' + esc(v.cable_output) + '».' +
        (v.cable_record ? (v.renamed ? ' Las demás apps lo ven como «' + esc(v.cable_record) + '».' : ' Las demás apps lo ven como «' + esc(v.cable_record) + '»: puedes renombrarlo (paso 2).') : '') + '</div></div>';
    } else {
      st.innerHTML = '<div class="notice warn">' + iconHTML('alert') + '<div><b>No se detecta ningún cable virtual.</b> Sin él, VoiceLab AI no puede crear un micrófono que vean otras aplicaciones. Instálalo con los pasos de abajo y pulsa «Actualizar dispositivos».</div></div>';
    }
    $('#cable-out-name').textContent = v.cable_output || 'CABLE Input';
    $$('.win-only').forEach((el) => { el.style.display = S.app.platform === 'win32' ? '' : 'none'; });
    renderChecklist();
  }

  function renderDerived() {
    const sr = getPath('audio.sample_rate') || 48000;
    const bs = getPath('audio.block_size') || 256;
    const nb = getPath('audio.buffer_blocks') || 2;
    const ms = (n) => (n / sr * 1000).toFixed(1).replace('.', ',');
    fillSelect($('#sel-block'), [64, 128, 256, 512, 1024].map((b) => ({ value: String(b), label: b + ' muestras · ' + ms(b) + ' ms' + (b === 256 ? ' (recomendado)' : '') })), String(bs));
    fillSelect($('#sel-buffer'), [1, 2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: n + (n === 1 ? ' bloque' : ' bloques') + ' · ' + ms(n * bs) + ' ms' + (n === 2 ? ' (recomendado)' : '') })), String(nb));
    const base = (bs * (nb + 1)) / sr * 1000;
    $('#latency-estimate').innerHTML = 'Con estos valores, la voz original tendrá unos <b>' + Math.round(base + 15) + '–' + Math.round(base + 35) +
      ' ms</b> de latencia total en WASAPI. Con el modulador activo verás la cifra real arriba a la derecha.';
  }

  // ================================================================== medidores
  const DB_FLOOR = -60;
  const frac = (db) => Math.max(0, Math.min(1, (db - DB_FLOOR) / -DB_FLOOR));

  class Meter {
    constructor(el, vertical) {
      this.el = el; this.vertical = vertical;
      this.fill = el.querySelector('.fill'); this.peakEl = el.querySelector('.peak');
      this.target = -120; this.shown = -120; this.hold = -120; this.holdT = 0;
    }
    set(db) { this.target = db; if (db > this.shown) this.shown = db; if (db >= this.hold) { this.hold = db; this.holdT = 1.2; } }
    tick(dt) {
      this.shown = Math.max(this.target, this.shown - 26 * dt);
      this.holdT -= dt;
      if (this.holdT <= 0) this.hold = Math.max(this.shown, this.hold - 20 * dt);
      const f = frac(this.shown), h = frac(this.hold);
      if (this.vertical) {
        this.fill.style.clipPath = 'inset(' + ((1 - f) * 100).toFixed(2) + '% 0 0 0)';
        if (this.peakEl) this.peakEl.style.bottom = 'calc(' + (h * 100).toFixed(2) + '% - 2px)';
      } else {
        this.fill.style.clipPath = 'inset(0 ' + ((1 - f) * 100).toFixed(2) + '% 0 0)';
        if (this.peakEl) this.peakEl.style.left = 'calc(' + (h * 100).toFixed(2) + '% - 2px)';
      }
      if (this.peakEl) this.peakEl.style.opacity = this.hold > -100 ? '.85' : '0';
    }
  }
  const meters = {};
  function setupMeters() {
    $$('[data-meter]').forEach((el) => { meters[el.dataset.meter] = new Meter(el, false); });
    $$('[data-vmeter]').forEach((el) => { meters[el.dataset.vmeter] = new Meter(el, true); });
  }
  let lastFrame = performance.now();
  function frame(now) {
    const dt = Math.min(0.1, (now - lastFrame) / 1000);
    lastFrame = now;
    for (const k in meters) meters[k].tick(dt);
    requestAnimationFrame(frame);
  }

  const SPECTRUM_BARS = 48;
  function setupSpectrum() {
    const box = $('#home-spectrum');
    box.innerHTML = '<i></i>'.repeat(SPECTRUM_BARS);
    S.history = new Array(SPECTRUM_BARS).fill(-120);
  }
  function pushSpectrum(db) {
    S.history.push(db); S.history.shift();
    if (S.page !== 'home') return;
    const bars = $('#home-spectrum').children;
    for (let i = 0; i < bars.length; i++) {
      const f = frac(S.history[i]);
      bars[i].style.height = (4 + f * 96).toFixed(1) + '%';
    }
  }

  // ===================================================================== estado
  function outputSource(st) {
    const r = st.routes;
    if (r.cable.active) return ['Micrófono virtual', r.cable];
    if (r.monitor.active) return ['Monitorización', r.monitor];
    if (r.aux.active) return ['Salida auxiliar', r.aux];
    return [st.running ? 'Voz procesada (ninguna salida activa)' : 'Voz procesada', st.processed];
  }

  function renderStatus() {
    const st = S.status;
    if (!st) return;
    const running = st.running, error = st.state === 'error';
    const lat = running ? st.latency_ms : null;

    // Barra superior y panel lateral
    $('#chip-latency-v').textContent = fmtMs(lat);
    $('#chip-state').className = 'chip' + (running ? ' ok' : error ? ' err' : '');
    $('#chip-dot').className = 'live-dot' + (running ? ' on' : error ? ' err' : '');
    $('#chip-state-t').textContent = running ? 'Activo' : error ? 'Error' : 'Detenido';
    $('#nav-live').className = 'live-dot' + (running ? ' on' : error ? ' err' : '');
    $('#dock-sub').textContent = running ? 'Activo · ' + fmtMs(lat) : error ? 'Error de audio' : 'Detenido';
    ['#dock-power', '#mod-power'].forEach((s) => $(s).classList.toggle('on', running));
    const hp = $('#home-power');
    hp.querySelector('span').textContent = running ? 'Detener modulador' : 'Activar modulador';
    hp.className = running ? 'btn' : 'btn primary';

    $('#mod-state').textContent = running ? 'Activo' : error ? 'Error' : 'Detenido';
    $('#mod-sub').innerHTML = running ? esc(st.sample_rate + ' Hz · bloque de ' + st.block_size + ' · CPU ' + Math.round((st.cpu_load || 0) * 100) + ' %')
      : 'Pulsa para empezar · <span class="kbd">Ctrl</span> + <span class="kbd">M</span>';
    const latHTML = (lat == null ? '—' : Math.round(lat)) + '<small>ms</small>';
    $('#mod-latency').innerHTML = latHTML;
    $('#home-latency').innerHTML = latHTML;

    // Medidores
    const inp = st.input;
    meters['in-peak'].set(inp.peak_db); meters['in-rms'].set(inp.rms_db);
    meters['dock-in'].set(inp.peak_db);
    $('#in-db').innerHTML = fmtDb(running ? inp.peak_db : null) + '<small> dB</small>';
    $('#in-clip').classList.toggle('on', !!inp.clip);
    $('#in-device').textContent = inp.device || 'Sin micrófono activo';
    const [outName, outM] = outputSource(st);
    meters['out-peak'].set(outM.peak_db); meters['out-rms'].set(outM.rms_db);
    meters['dock-out'].set(outM.peak_db);
    $('#out-db').innerHTML = fmtDb(running ? outM.peak_db : null) + '<small> dB</small>';
    $('#out-clip').classList.toggle('on', !!outM.clip);
    $('#out-target').textContent = outName;
    pushSpectrum(running ? inp.rms_db : -120);

    // Puerta de ruido
    const gateLed = $('#gate-led');
    gateLed.className = 'led' + (!running || !inp.gate_enabled ? '' : inp.gate_open ? ' on' : ' off');
    $('#gate-state').textContent = !inp.gate_enabled ? 'desactivada' : !running ? '' : inp.gate_open ? 'abierta' : 'cerrada';
    $('#mod-input-name').textContent = inp.device || (S.devices && (getPath('audio.input_device') || S.devices.defaults.input)) || 'Sin micrófono';

    // Rutas
    for (const r of ROUTES) {
      const info = st.routes[r.key];
      const row = $('[data-route="' + r.key + '"]');
      row.classList.toggle('on', info.enabled);
      const badge = row.querySelector('[data-r="badge"]');
      if (!info.enabled) { badge.textContent = 'Desactivada'; badge.style.cssText = ''; }
      else if (info.active) { badge.textContent = 'Enviando'; badge.style.cssText = 'background:var(--ok-soft);color:var(--ok)'; }
      else if (info.error) { badge.textContent = 'Error'; badge.style.cssText = 'background:var(--danger-soft);color:var(--danger)'; }
      else { badge.textContent = running ? 'Preparando' : 'Lista'; badge.style.cssText = ''; }
      row.querySelector('[data-r="lat"]').textContent = info.active ? fmtMs(info.latency_ms) : '—';
      row.querySelector('[data-r="under"]').textContent = info.underruns || 0;
      row.querySelector('[data-r="limit"]').innerHTML = info.limiting ? '<span style="color:var(--warn)">Limitador actuando</span>' : '';
      meters['route-' + r.key].set(info.active ? info.peak_db : -120);
      if (r.key === 'cable') {
        const sm = st.system_mic, box = row.querySelector('[data-r="sysmic"]');
        let t = '';
        if (sm && sm.error) t = '<div class="notice warn">' + iconHTML('alert') + '<div>' + esc(sm.error) + '</div></div>';
        else if (sm && sm.engaged) t = '<div class="small" style="color:var(--ok)">' + iconHTML('check') + ' Ahora el micrófono predeterminado de Windows es «' + esc(sm.device || 'CABLE Output') + '». Si un programa ya estaba abierto y no te oye modulado, elige «Predeterminado» como micrófono o reinícialo.</div>';
        if (box && box.dataset.html !== t) { box.dataset.html = t; box.innerHTML = t; }
      }
      const errBox = row.querySelector('[data-r="error"]');
      const errText = info.enabled && info.error ? info.error : '';
      if (errBox.dataset.text !== errText) {
        errBox.dataset.text = errText;
        errBox.innerHTML = errText ? '<div class="notice err">' + iconHTML('alert') + '<div>' + esc(errText) + '</div></div>' : '';
      }
      if (errText && S.lastRouteErrors[r.key] !== errText) toast('err', errText);
      S.lastRouteErrors[r.key] = errText;
    }

    if (st.error && st.error !== S.lastError) toast('err', st.error);
    S.lastError = st.error;
    if (running && inp.peak_db > -50 && !S.sawSignal) { S.sawSignal = true; renderChecklist(); }
  }

  async function pollLoop() {
    for (;;) {
      const res = await call('get_status');
      if (res && res.ok) { S.status = res; renderStatus(); }
      await sleep(S.status && S.status.running ? 50 : 400);
    }
  }

  // ===================================================================== motor
  async function toggleEngine() {
    if (S.busy) return;
    S.busy = true;
    $$('.power').forEach((b) => b.classList.add('busy'));
    const wasRunning = S.status && S.status.running;
    const res = await call(wasRunning ? 'stop_engine' : 'start_engine');
    $$('.power').forEach((b) => b.classList.remove('busy'));
    S.busy = false;
    if (res.status) { S.status = res.status; renderStatus(); }
    if (!res.ok) toast('err', res.error || 'No se pudo iniciar el audio.');
    else if (!wasRunning) renderChecklist();
    trackJob(res);
  }

  // Tareas lanzadas al activar el motor o un perfil (cargar la voz de IA):
  // se muestran en la barra de progreso y sus errores no se pierden.
  function trackJob(res) {
    if (!res || !res.ok || !res.job || !window.VLStudio) return;
    window.VLStudio.runJob({ ok: true, job: res.job }).then((r) => {
      if (r && r.ai) toast('ok', 'Voz de IA activa en el modulador.');
      document.dispatchEvent(new CustomEvent('vl:settings'));
    });
  }

  // ======================================================= aviso de monitor
  const HEADPHONES = /auricular|cascos?|headphone|headset|earphone|earbud|buds|airpods|in-ear/i;
  function confirmMonitor() {
    const dev = getPath('audio.monitor_device') || (S.devices && S.devices.defaults.monitor) || '';
    if (S.settings.ui.monitor_warning_ack || HEADPHONES.test(dev)) return Promise.resolve(true);
    $('#modal-text').textContent = 'Vas a escuchar tu voz por «' + (dev || 'la salida predeterminada') + '». Si son altavoces, el micrófono puede captar el sonido y producir acople (un pitido creciente). Usa auriculares si puedes. El limitador de seguridad reduce el riesgo, pero no lo elimina.';
    $('#modal-remember').checked = false;
    $('#modal').classList.add('open');
    return new Promise((resolve) => {
      const done = (ok) => {
        $('#modal').classList.remove('open');
        $('#modal-ok').onclick = $('#modal-cancel').onclick = null;
        if (ok && $('#modal-remember').checked) sendSetting('ui.monitor_warning_ack', true, { quiet: true });
        resolve(ok);
      };
      $('#modal-ok').onclick = () => done(true);
      $('#modal-cancel').onclick = () => done(false);
    });
  }

  // ===================================================================== inicio
  function renderChecklist() {
    if (!S.devices || !S.settings) return;
    const d = S.devices, v = d.virtual || {};
    const running = S.status && S.status.running;
    const mic = getPath('audio.input_device') || d.defaults.input;
    const items = [];
    items.push(mic && d.available
      ? { s: 'ok', t: 'Micrófono', sub: mic }
      : { s: 'err', t: 'Micrófono', sub: (d.error || 'No se detecta ningún micrófono'), act: ['settings', 'Revisar'] });
    items.push(v.cable_output
      ? { s: 'ok', t: 'Micrófono virtual', sub: v.is_vbcable ? 'VB-CABLE instalado' : 'Dispositivo virtual: ' + v.cable_output }
      : { s: 'warn', t: 'Micrófono virtual', sub: 'Instala VB-CABLE para usar tu voz en otras apps', act: ['settings', 'Cómo instalarlo'] });
    if (!v.cable_output) items.push({ s: 'pending', t: 'Nombre «VoiceLab AI Microphone»', sub: 'Primero instala el cable virtual' });
    else if (v.renamed) items.push({ s: 'ok', t: 'Nombre «VoiceLab AI Microphone»', sub: 'Las apps lo ven como «' + v.cable_record + '»' });
    else items.push({ s: 'warn', t: 'Nombre «VoiceLab AI Microphone»', sub: 'Opcional: renombra «CABLE Output» en Windows', act: ['settings', 'Ver pasos'] });
    items.push(S.sawSignal
      ? { s: 'ok', t: 'Prueba de voz', sub: 'Señal recibida del micrófono' }
      : running ? { s: 'warn', t: 'Prueba de voz', sub: 'Habla: el medidor de entrada debería moverse' }
        : { s: 'pending', t: 'Prueba de voz', sub: 'Activa el modulador y di algo' });
    const ico = { ok: 'check', warn: 'alert', err: 'x', pending: 'chevron' };
    $('#checklist').innerHTML = items.map((i) =>
      '<div class="check ' + i.s + '"><div class="check-ico">' + iconHTML(ico[i.s]) + '</div>' +
      '<div style="min-width:0"><div class="check-title">' + esc(i.t) + '</div><div class="check-sub">' + esc(i.sub) + '</div></div>' +
      (i.act ? '<button class="link small" data-goto="' + i.act[0] + '">' + esc(i.act[1]) + '</button>' : '<span></span>') + '</div>').join('');
  }

  function renderSystem() {
    const sys = S.system || {};
    const gpus = (sys.gpus || []).map((g) => g.name + (g.vram_gb ? ' · ' + g.vram_gb + ' GB' : '')).join(', ') || 'No detectada';
    const rows = [
      ['windows', 'Sistema', sys.os || '—'],
      ['cpu', 'Procesador', (sys.cpu || '—') + (sys.cpu_threads ? ' · ' + sys.cpu_threads + ' hilos' : '')],
      ['ram', 'Memoria', sys.ram_gb ? sys.ram_gb + ' GB' : '—'],
      ['gpu', 'Gráfica', gpus],
      ['sparkles', 'Motor de IA', (sys.ai && sys.ai.summary) || '—'],
    ];
    const html = rows.map((r) => '<dt>' + iconHTML(r[0]) + esc(r[1]) + '</dt><dd title="' + esc(r[2]) + '">' + esc(r[2]) + '</dd>').join('');
    $('#home-system').innerHTML = html;
    const pa = S.devices && S.devices.portaudio;
    $('#settings-system').innerHTML = html + '<dt>' + iconHTML('speaker') + 'Audio</dt><dd>' + esc(pa || 'No disponible') + '</dd>';
    $('#about').innerHTML = 'VoiceLab AI v' + esc(S.app.version) + ' · Fase ' + S.app.phase + '. Todo se procesa y se guarda en este equipo: sin cuentas, sin suscripciones y sin servicios de pago.';
  }

  const PHASES = [
    ['Interfaz y sistema de dispositivos', 'Motor en tiempo real, medidores, latencia, rutas de salida'],
    ['Micrófono virtual y efectos tradicionales', 'Pitch, formantes, EQ, compresor, reverberación, preajustes'],
    ['Clonación de voz con IA', 'Importar audio/vídeo, limpieza, perfiles Chatterbox y RVC'],
    ['Conversión de voz en tiempo real', 'RVC (ONNX + DirectML) y voz instantánea en directo sin entrenar (MeanVC2, experimental)'],
    ['Texto a voz', 'Chatterbox Multilingual, historial, exportación'],
    ['Editor de audio y biblioteca', 'Forma de onda, cortes, carpetas, copias de seguridad'],
    ['Optimización e instalador', 'Ejecutable, instalador y desinstalador de Windows'],
  ];
  function renderRoadmap() {
    const STATUS = ['Hecha', 'Hecha', 'Hecha', 'Probar con modelo', 'Probar con modelo', 'Hecha', 'Compilar .exe'];
    $('#roadmap').innerHTML = PHASES.map((p, i) => {
      const n = i + 1, label = STATUS[i], cls = label === 'Hecha' ? 'done' : 'current';
      return '<div class="phase ' + cls + '"><div class="phase-num">' + n + '</div><div><div class="phase-title">' + esc(p[0]) + '</div><div class="phase-sub">' + esc(p[1]) + '</div></div><span class="badge">' + label + '</span></div>';
    }).join('');
  }

  // ===================================================================== eventos
  function bindEvents() {
    $$('.nav-item').forEach((b) => b.addEventListener('click', () => showPage(b.dataset.page)));
    document.addEventListener('click', async (e) => {
      const g = e.target.closest('[data-goto]');
      if (g) { showPage(g.dataset.goto); return; }
      const ext = e.target.closest('[data-external]');
      if (ext) {
        const r = await call('open_external', ext.dataset.external);
        if (!r.ok) toast('err', r.error);
        return;
      }
      const sp = e.target.closest('[data-sound-panel]');
      if (sp) {
        const r = await call('open_sound_panel', sp.dataset.soundPanel);
        if (!r.ok) toast('err', r.error);
        return;
      }
      const tone = e.target.closest('[data-tone]');
      if (tone) {
        tone.disabled = true;
        const r = await call('play_test_tone', tone.dataset.tone);
        setTimeout(() => { tone.disabled = false; }, 900);
        toast(r.ok ? 'info' : 'err', r.ok ? r.hint : r.error, r.ok ? 7000 : undefined);
      }
    });
    ['#dock-power', '#mod-power', '#home-power'].forEach((s) => $(s).addEventListener('click', toggleEngine));
    $('#btn-refresh').addEventListener('click', async () => {
      const b = $('#btn-refresh');
      b.disabled = true;
      const r = await call('refresh_devices');
      b.disabled = false;
      if (r.devices) { S.devices = r.devices; renderDevices(); applySettingsToControls(); }
      if (r.status) { S.status = r.status; renderStatus(); }
      toast(r.ok ? 'ok' : 'err', r.ok ? 'Lista de dispositivos actualizada.' : r.error);
    });
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && !e.shiftKey && !e.altKey && (e.key === 'm' || e.key === 'M')) { e.preventDefault(); toggleEngine(); }
      if (e.key === 'Escape' && $('#modal').classList.contains('open')) $('#modal-cancel').click();
    });
    $$('[data-range]').forEach(setupRange);
    $$('[data-switch]').forEach(setupSwitch);
    $$('select[data-select]').forEach(setupSelect);
  }

  // ===================================================================== arranque
  async function boot() {
    hydrateIcons();
    renderSoonPages();
    buildRoutes();
    setupMeters();
    setupSpectrum();
    bindEvents();
    const res = await call('get_initial_state');
    if (!res || !res.ok) {
      $('#boot-msg').innerHTML = esc((res && res.error) || 'No se pudo conectar con el motor de audio.') +
        ' <button class="btn sm" onclick="location.reload()">Reintentar</button>';
      return;
    }
    Object.assign(S, { app: res.app, settings: res.settings, devices: res.devices, status: res.status, system: res.system });
    $('#brand-sub').textContent = 'Fase ' + S.app.phase + ' · v' + S.app.version;
    renderDevices();
    renderDerived();
    applySettingsToControls();
    renderSystem();
    renderRoadmap();
    renderStatus();
    renderChecklist();
    if (setupLanguage()) return;
    showPage(S.settings.ui.last_page || 'home', false);
    $('#boot').classList.add('hide');
    call('ui_ready', Math.round(performance.now()));
    requestAnimationFrame(frame);
    pollLoop();
    document.dispatchEvent(new CustomEvent('vl:ready'));
  }

  // ======================================================== idioma
  // Devuelve true si hay que recargar porque el idioma guardado en los ajustes
  // no es el que se ha aplicado (por ejemplo, tras reinstalar).
  function setupLanguage() {
    const I = window.VL_I18N;
    const sel = $('#ui-lang');
    if (!I || !sel) return false;
    const want = (S.settings.ui && S.settings.ui.language) || 'auto';
    if (!I.forced && I.pref !== want && I.remember(want)) { location.reload(); return true; }
    const auto = I.names[I.resolve('auto')] || I.names.en;
    sel.innerHTML = '<option value="auto">' + esc(I.t('Automático (' + auto + ')')) + '</option>' +
      I.supported.map(c => '<option value="' + c + '">' + esc(I.names[c]) + '</option>').join('');
    sel.value = want;
    sel.addEventListener('change', async () => {
      const v = sel.value;
      await sendSetting('ui.language', v, { quiet: true });
      if (I.remember(v)) location.reload();
    });
    return false;
  }

  function applyResponse(res, quiet) {
    if (!res) return res;
    if (res.settings) S.settings = res.settings;
    if (res.devices) { S.devices = res.devices; renderDevices(); }
    if (res.status) { S.status = res.status; renderStatus(); }
    if (!res.ok && res.error && !res.needs_upload && !quiet) toast('err', res.error);
    document.dispatchEvent(new CustomEvent('vl:settings'));
    trackJob(res);
    return res;
  }

  // Traducción para lo que no pasa por el DOM tal cual (opciones de <select>, fechas…).
  const t = (s) => (window.VL_I18N ? window.VL_I18N.t(s) : s);
  window.VL = { S, call, toast, esc, showPage, applyResponse, sendSetting, t, $, $$ };
  document.addEventListener('DOMContentLoaded', boot);
})();
