/* Fases 3 y 6: importar, forma de onda, clonar, grabar y editor de audio. */
(function () {
  'use strict';
  let VL, $, $$;
  const views = {};
  const state = { clone: null, editor: null, items: [], checked: new Set() };
  const fmtT = (s) => { s = Math.max(0, s || 0); const m = Math.floor(s / 60); return m + ':' + (s % 60).toFixed(1).padStart(4, '0'); };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ------------------------------------------------------------- tareas
  async function runJob(res) {
    if (!res.ok) { if (!res.needs_upload && !res.cancelled) VL.toast('err', res.error); return null; }
    if (!res.job) return res;
    const bar = $('#jobbar');
    for (;;) {
      const r = await VL.call('get_job', res.job);
      const j = r.job;
      if (!j) return null;
      bar.hidden = false;
      $('#jobbar-label').textContent = j.detail ? j.label + ' · ' + j.detail : j.label + '…';
      $('#jobbar-fill').style.width = Math.round(j.progress * 100) + '%';
      if (j.state !== 'running') {
        bar.hidden = true;
        if (j.state === 'error') { VL.toast(j.cancelled ? 'info' : 'err', j.cancelled ? 'Cancelado.' : j.error); return null; }
        return j.result === null ? {} : j.result;
      }
      await sleep(150);
    }
  }

  // --------------------------------------------------- forma de onda
  class WaveView {
    constructor(el, onChange) {
      this.el = el; this.onChange = onChange;
      el.innerHTML = '<canvas></canvas><div class="sel"></div><div class="cursor"></div><div class="head"></div>';
      this.canvas = el.querySelector('canvas');
      this.sel = null; this.cursor = 0; this.wave = []; this.duration = 0; this.head = null;
      let down = null;
      const t = (e) => { const r = el.getBoundingClientRect(); return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * this.duration; };
      el.addEventListener('mousedown', (e) => { down = t(e); this.cursor = down; this.sel = null; this.draw(); });
      window.addEventListener('mousemove', (e) => { if (down === null) return; const x = t(e); this.sel = Math.abs(x - down) > this.duration / 500 ? [Math.min(x, down), Math.max(x, down)] : null; this.draw(); });
      window.addEventListener('mouseup', () => { if (down !== null) { down = null; this.onChange && this.onChange(); } });
      new ResizeObserver(() => this.draw()).observe(el);
    }
    set(wave, duration) { this.wave = wave; this.duration = duration; this.sel = null; this.cursor = 0; this.draw(); }
    range() { return this.sel ? { start: this.sel[0], end: this.sel[1] } : { start: null, end: null }; }
    draw() {
      const c = this.canvas, w = this.el.clientWidth, h = this.el.clientHeight, dpr = window.devicePixelRatio || 1;
      c.width = w * dpr; c.height = h * dpr; c.style.width = w + 'px'; c.style.height = h + 'px';
      const g = c.getContext('2d'); g.scale(dpr, dpr); g.clearRect(0, 0, w, h);
      const grad = g.createLinearGradient(0, 0, w, 0); grad.addColorStop(0, '#8b5cf6'); grad.addColorStop(1, '#22d3ee');
      g.fillStyle = grad;
      const n = this.wave.length, mid = h / 2;
      for (let x = 0; x < w && n; x++) {
        const a = Math.floor(x / w * n), b = Math.max(a + 1, Math.floor((x + 1) / w * n));
        let lo = 0, hi = 0;
        for (let i = a; i < b && i < n; i++) { lo = Math.min(lo, this.wave[i][0]); hi = Math.max(hi, this.wave[i][1]); }
        g.fillRect(x, mid - hi * mid * 0.95, 1, Math.max(1, (hi - lo) * mid * 0.95));
      }
      const px = (s) => (this.duration ? s / this.duration * 100 : 0) + '%';
      const selEl = this.el.querySelector('.sel');
      selEl.style.display = this.sel ? 'block' : 'none';
      if (this.sel) { selEl.style.left = px(this.sel[0]); selEl.style.width = (this.sel[1] - this.sel[0]) / (this.duration || 1) * 100 + '%'; }
      this.el.querySelector('.cursor').style.left = px(this.cursor);
      const hd = this.el.querySelector('.head');
      hd.style.display = this.head === null ? 'none' : 'block';
      if (this.head !== null) hd.style.left = px(this.head);
    }
    info() {
      return this.sel ? 'Selección ' + fmtT(this.sel[0]) + ' – ' + fmtT(this.sel[1]) + ' (' + (this.sel[1] - this.sel[0]).toFixed(1) + ' s)'
        : 'Cursor ' + fmtT(this.cursor) + ' · Total ' + fmtT(this.duration);
    }
  }

  async function loadInto(key, id) {
    const r = await VL.call('get_item', id, 2400);
    if (!r.ok) { VL.toast('err', r.error); return; }
    state[key] = r.item;
    views[key].set(r.wave, r.item.duration);
    $('[data-wave-info="' + key + '"]').textContent = views[key].info();
    return r.item;
  }

  // ------------------------------------------------------ importación
  async function uploadFile(file) {
    const b = await VL.call('upload_begin', file.name, file.size);
    if (!b.ok) { VL.toast('err', b.error); return null; }
    const CH = 2 * 1024 * 1024, bar = $('#jobbar');
    bar.hidden = false;
    for (let off = 0; off < file.size; off += CH) {
      $('#jobbar-label').textContent = 'Cargando ' + file.name + '…';
      $('#jobbar-fill').style.width = Math.round(off / file.size * 100) + '%';
      const data = await new Promise((res) => { const rd = new FileReader(); rd.onload = () => res(rd.result.split(',')[1] || ''); rd.readAsDataURL(file.slice(off, off + CH)); });
      const c = await VL.call('upload_chunk', b.upload, data);
      if (!c.ok) { bar.hidden = true; VL.toast('err', c.error); return null; }
    }
    return runJob(await VL.call('upload_finish', b.upload));
  }

  async function importFor(target, files) {
    let item = null;
    if (files && files.length) {
      for (const f of files) item = await uploadFile(f) || item;
    } else {
      const r = await VL.call('import_media');
      if (r.needs_upload) { pickerTarget = target; $('#studio-file').click(); return; }
      item = await runJob(r);
    }
    if (!item) return;
    if (item.was_video) VL.toast('ok', 'Audio extraído del vídeo «' + item.source + '».');
    await refreshItems();
    if (target === 'clone') selectClone(item.id); else openEditor(item.id);
  }
  let pickerTarget = 'editor';

  // ------------------------------------------------------------ clonar
  async function selectClone(id) {
    $('[data-item-select="clone"]').value = id;
    $('#clone-step2').hidden = false;
    $('#clone-analysis').innerHTML = '';
    $('#clone-step3').hidden = true;
    const item = await loadInto('clone', id);
    if (item && !$('#clone-name').value) $('#clone-name').value = item.name;
  }

  async function analyzeClone() {
    if (!state.clone) return;
    const r = views.clone.range();
    const a = await runJob(await VL.call('analyze_item', state.clone.id, r.start, r.end));
    if (!a) return;
    const tiers = ['insufficient', 'instant', 'rvc_basic', 'rvc_good'];
    const pct = Math.min(100, a.speech_s / 600 * 100);
    $('#clone-analysis').innerHTML =
      '<div class="analysis">' +
      '<div class="kpi"><b class="num">' + a.speech_s.toFixed(0) + ' s</b><span>de voz útil</span></div>' +
      '<div class="kpi"><b class="num">' + a.snr_db.toFixed(0) + ' dB</b><span>señal / ruido</span></div>' +
      '<div class="kpi"><b class="num">' + (a.f0_median ? Math.round(a.f0_median) + ' Hz' : '—') + '</b><span>tono medio' + (a.f0_p10 ? ' (' + Math.round(a.f0_p10) + '–' + Math.round(a.f0_p90) + ')' : '') + '</span></div>' +
      '<div class="kpi"><b class="num">' + a.level_db.toFixed(0) + ' dB</b><span>nivel de la voz</span></div></div>' +
      '<div class="suff"><div class="suff-bar"><i style="width:' + pct + '%"></i><em style="left:' + (10 / 6) + '%"></em><em style="left:50%"></em><em style="left:100%"></em></div>' +
      '<div class="suff-labels small muted"><span>10 s · instantánea</span><span>5 min · voz fiel</span><span>10 min · voz fiel ideal</span></div></div>' +
      '<div class="notice ' + (a.tier === 'insufficient' ? 'err' : 'ok') + '">' + iconHTML(a.tier === 'insufficient' ? 'alert' : 'check') + '<div><b>' + VL.esc(a.tier_label) + '.</b></div></div>' +
      a.warnings.map((w) => '<div class="notice warn">' + iconHTML('alert') + '<div>' + VL.esc(w) + '</div></div>').join('');
    $('#clone-step3').hidden = a.tier === 'insufficient';
    void tiers;
  }

  async function createClone() {
    const consent = (VL.$('input[name="consent"]:checked') || {}).value;
    if (!consent) { VL.toast('err', 'Indica si la voz es tuya o si tienes autorización de la persona.'); return; }
    const r = views.clone.range();
    const prof = await runJob(await VL.call('create_voice_profile', {
      item_id: state.clone.id, start: r.start, end: r.end, name: $('#clone-name').value, folder: $('#clone-folder').value,
      description: $('#clone-desc').value, language: $('#clone-lang').value, clean: $('#clone-clean').checked,
      consent_own: consent === 'own', consent_authorized: consent === 'authorized' }));
    if (!prof) return;
    VL.toast('ok', 'Voz «' + prof.name + '» creada con ' + prof.cloning.analysis.speech_s.toFixed(0) + ' s de voz. Ya puedes usarla en Texto a voz o hablar con ella en directo.');
    VL.applyResponse(await VL.call('activate_profile', prof.id));
    document.dispatchEvent(new CustomEvent('vl:profiles'));
    VL.showPage('modulator');
  }

  // ------------------------------------------------------------ grabar
  const TEXTS = [
    'Esta mañana el cielo amaneció despejado. Cogí la bicicleta, crucé el puente viejo y llegué al mercado justo cuando abrían los puestos de fruta. ¿Quién no disfruta del olor a pan recién hecho?',
    'Mi abuela guardaba recetas en una caja de lata: churros, gazpacho, paella y un bizcocho de yogur que nunca salía igual. Decía que el secreto era la paciencia, y quizá un poco de suerte.',
    '¡Qué sorpresa! Ayer encontré un mapa antiguo dentro de un libro de geografía. Marcaba un camino desde la playa hasta una cueva escondida entre pinos, rocas y zarzas.',
    'Por favor, apunta estos números: cuatro, quince, veintiocho y noventa y seis. Si llamas antes de las seis, pregunta por Jorge o por Ximena; ellos sabrán ayudarte.',
    'El tren se retrasó casi una hora por la niebla. Mientras esperábamos, un señor con sombrero contó historias de viajes por Chile, Japón y Marruecos. Nadie se aburrió.',
  ];
  let textIdx = 0, recTimer = null;
  function showText() { $('#read-text').textContent = TEXTS[textIdx % TEXTS.length]; }

  async function toggleRec() {
    const btn = $('#rec-btn');
    if (btn.classList.contains('on')) {
      clearInterval(recTimer);
      btn.classList.remove('on');
      const r = await VL.call('stop_recording');
      if (!r.ok) { VL.toast('err', r.error); return; }
      VL.toast('ok', 'Grabación guardada (' + r.item.duration.toFixed(1) + ' s).');
      refreshItems();
      return;
    }
    const r = await VL.call('start_recording');
    if (!r.ok) { VL.toast('err', r.error); return; }
    $('#rec-device').textContent = 'Micrófono: ' + r.device;
    btn.classList.add('on');
    recTimer = setInterval(async () => {
      const s = (await VL.call('playback_status')).recorder;
      if (!s) return;
      const sec = Math.floor(s.seconds);
      $('#rec-time').textContent = String(Math.floor(sec / 60)).padStart(2, '0') + ':' + String(sec % 60).padStart(2, '0');
      VL.meters && VL.meters.rec && VL.meters.rec.set(s.peak_db);
    }, 120);
  }

  // ------------------------------------------------------------ listas
  async function refreshItems() {
    const r = await VL.call('list_items');
    if (!r.ok) return;
    state.items = r.items;
    const opts = '<option value="">o usa un audio que ya tengas en VoiceLab…</option>' + r.items.map((i) => '<option value="' + i.id + '">' + VL.esc(i.name) + ' · ' + fmtT(i.duration) + '</option>').join('');
    const sel = $('[data-item-select="clone"]'); const cur = sel.value; sel.innerHTML = opts; sel.value = cur;
    const kinds = { import: 'Importado', recording: 'Grabación', edit: 'Editado', tts: 'Texto a voz' };
    $('#ed-list').innerHTML = r.items.length ? r.items.map((i) =>
      '<div class="ed-item' + (state.editor && state.editor.id === i.id ? ' active' : '') + '" data-open="' + i.id + '">' +
      '<input type="checkbox" data-check="' + i.id + '"' + (state.checked.has(i.id) ? ' checked' : '') + ' aria-label="Seleccionar para unir">' +
      '<div style="min-width:0"><div class="ed-item-name">' + VL.esc(i.name) + '</div><div class="small muted">' + VL.esc(VL.t(kinds[i.kind] || '')) + ' · ' + fmtT(i.duration) + '</div></div></div>').join('')
      : '<div class="small muted" style="padding:8px 2px">Sin audios todavía.</div>';
    const recs = r.items.filter((i) => i.kind === 'recording');
    $('#rec-list').innerHTML = recs.length ? recs.map((i) =>
      '<div class="rec-row"><div class="grow"><b>' + VL.esc(i.name) + '</b> <span class="small muted num">' + fmtT(i.duration) + '</span></div>' +
      '<button class="btn sm" data-rec-play="' + i.id + '">' + iconHTML('play') + 'Escuchar</button>' +
      '<button class="btn sm ghost" data-rec-edit="' + i.id + '">Abrir en el editor</button>' +
      '<button class="btn sm ghost" data-rec-clone="' + i.id + '">Usar para clonar</button></div>').join('')
      : '<div class="small muted">Pulsa el botón rojo para grabar tu primera toma.</div>';
    $('#ed-join').disabled = state.checked.size < 2;
  }

  // ------------------------------------------------------------ editor
  async function openEditor(id) {
    VL.showPage('editor');
    $('#ed-empty').hidden = true; $('#ed-work').hidden = false;
    const item = await loadInto('editor', id);
    if (!item) return;
    $('#ed-name').value = item.name;
    $('#ed-dur').textContent = fmtT(item.duration);
    refreshItems();
  }

  async function editorOp(op) {
    const it = state.editor;
    if (!it) return;
    const r = views.editor.range();
    const args = { start: r.start, end: r.end };
    if (['crop', 'delete', 'silence', 'fade_in', 'fade_out'].includes(op) && r.start === null) { VL.toast('err', 'Selecciona primero un tramo arrastrando sobre la onda.'); return; }
    if (op === 'delete_item' && !window.confirm('¿Eliminar «' + it.name + '» del espacio de trabajo?')) return;
    if (op === 'gain') args.db = parseFloat($('#ed-db').value) || 0;
    if (op === 'speed' || op === 'tempo') args.rate = parseFloat($('#ed-rate').value) || 1;
    if (op === 'split') args.at = views.editor.cursor;
    if (op === 'effects') {
      const v = $('#ed-fx').value;
      if (v === 'current') args.params = VL.S.settings.voice.params;
      else if (v.startsWith('preset:')) args.params = (await VL.call('get_effects_schema')).presets.find((p) => p.id === v.slice(7)).params;
      else if (v.startsWith('profile:')) args.params = (await VL.call('list_profiles')).profiles.find((p) => p.id === v.slice(8)).effects;
    }
    const res = await runJob(await VL.call('edit_item', it.id, op, args));
    if (res === null) return;
    if (op === 'delete_item') { state.editor = null; $('#ed-work').hidden = true; $('#ed-empty').hidden = false; await refreshItems(); return; }
    if (op === 'duplicate' || op === 'split') VL.toast('ok', op === 'split' ? 'Audio dividido en dos.' : 'Audio duplicado.');
    await loadInto('editor', it.id);
    $('#ed-dur').textContent = fmtT(state.editor.duration);
    refreshItems();
  }

  async function fillFxSelect() {
    const [sc, pr] = await Promise.all([VL.call('get_effects_schema'), VL.call('list_profiles')]);
    $('#ed-fx').innerHTML = '<option value="current">Ajustes actuales del modulador</option>' +
      '<optgroup label="Preajustes">' + (sc.presets || []).map((p) => '<option value="preset:' + p.id + '">' + VL.esc(p.label) + '</option>').join('') + '</optgroup>' +
      ((pr.profiles || []).filter((p) => p.type === 'effects').length ? '<optgroup label="Perfiles">' + pr.profiles.filter((p) => p.type === 'effects').map((p) => '<option value="profile:' + p.id + '">' + VL.esc(p.name) + '</option>').join('') + '</optgroup>' : '');
  }

  // ------------------------------------------------- reproducción común
  let playTimer = null, playing = null;
  async function play(key, id, start, end) {
    const r = await VL.call('play_item', id, start, end);
    if (!r.ok) { VL.toast('err', r.error); return; }
    playing = key;
    clearInterval(playTimer);
    playTimer = setInterval(async () => {
      const s = (await VL.call('playback_status')).player;
      const v = views[playing];
      if (v) { v.head = s.playing ? s.position : null; v.draw(); }
      if (!s.playing) clearInterval(playTimer);
    }, 80);
  }

  // ----------------------------------------------------------- arranque
  function init() {
    VL = window.VL; $ = VL.$; $$ = VL.$$;
    document.body.insertAdjacentHTML('beforeend', '<input type="file" id="studio-file" multiple hidden accept=".mp3,.wav,.flac,.m4a,.aac,.ogg,.opus,.mp4,.mkv,.mov,.webm">');
    hydrateIcons();
    ['clone', 'editor'].forEach((k) => {
      views[k] = new WaveView($('[data-wave="' + k + '"]'), () => { $('[data-wave-info="' + k + '"]').textContent = views[k].info(); });
    });
    $('#studio-file').addEventListener('change', (e) => { const f = [...e.target.files]; e.target.value = ''; importFor(pickerTarget, f); });
    $$('[data-import]').forEach((b) => b.addEventListener('click', () => importFor(b.dataset.import)));
    $$('[data-drop]').forEach((z) => {
      z.addEventListener('dragover', (e) => { e.preventDefault(); z.classList.add('over'); });
      z.addEventListener('dragleave', () => z.classList.remove('over'));
      z.addEventListener('drop', (e) => { e.preventDefault(); z.classList.remove('over'); importFor(z.dataset.drop, [...e.dataTransfer.files]); });
    });
    $('[data-item-select="clone"]').addEventListener('change', (e) => { if (e.target.value) selectClone(e.target.value); });
    $('#clone-analyze').addEventListener('click', analyzeClone);
    $('#clone-create').addEventListener('click', createClone);
    $$('[data-play]').forEach((b) => b.addEventListener('click', () => {
      const k = b.dataset.play, it = state[k];
      if (!it) return;
      const r = views[k].range();
      play(k, it.id, r.start !== null ? r.start : views[k].cursor, r.end);
    }));
    $$('[data-stop]').forEach((b) => b.addEventListener('click', () => VL.call('stop_playback')));
    $('#rec-btn').addEventListener('click', toggleRec);
    $('#read-next').addEventListener('click', () => { textIdx++; showText(); });
    showText();
    $('#rec-list').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.recPlay) play('none', b.dataset.recPlay);
      if (b.dataset.recEdit) openEditor(b.dataset.recEdit);
      if (b.dataset.recClone) { VL.showPage('clone'); selectClone(b.dataset.recClone); }
    });
    $('#ed-list').addEventListener('click', (e) => {
      const c = e.target.closest('[data-check]');
      if (c) { c.checked ? state.checked.add(c.dataset.check) : state.checked.delete(c.dataset.check); $('#ed-join').disabled = state.checked.size < 2; return; }
      const o = e.target.closest('[data-open]');
      if (o) openEditor(o.dataset.open);
    });
    $('#ed-join').addEventListener('click', async () => {
      const ids = state.items.filter((i) => state.checked.has(i.id)).map((i) => i.id).reverse();
      const it = await runJob(await VL.call('join_items', ids, 'Audio unido'));
      if (it) { state.checked.clear(); openEditor(it.id); }
    });
    $$('[data-op]').forEach((b) => b.addEventListener('click', () => editorOp(b.dataset.op)));
    $('#ed-name').addEventListener('change', async () => { if (state.editor) { await runJob(await VL.call('edit_item', state.editor.id, 'rename', { name: $('#ed-name').value })); refreshItems(); } });
    $('#ed-export').addEventListener('click', async () => {
      if (!state.editor) return;
      const r = views.editor.range();
      const res = await runJob(await VL.call('export_item', state.editor.id, $('#ed-fmt').value, r.start, r.end));
      if (res && res.path) { VL.toast('ok', 'Exportado: ' + res.path); if (VL.S.app.platform === 'win32') VL.call('reveal_path', res.path); }
    });
    $('#ed-to-clone').addEventListener('click', () => { if (state.editor) { VL.showPage('clone'); selectClone(state.editor.id); } });
    document.addEventListener('vl:page', (e) => {
      if (['clone', 'create', 'editor'].includes(e.detail)) refreshItems();
      if (e.detail === 'editor') fillFxSelect();
      if (e.detail !== 'create' && $('#rec-btn').classList.contains('on')) { /* la grabación sigue en segundo plano */ }
    });
    const recMeter = $('[data-meter="rec"]');
    VL.meters = VL.meters || {};
    VL.meters.rec = { set: (db) => { const f = Math.max(0, Math.min(1, (db + 60) / 60)); recMeter.querySelector('.fill').style.clipPath = 'inset(0 ' + ((1 - f) * 100).toFixed(1) + '% 0 0)'; } };
    refreshItems();
  }

  document.addEventListener('vl:ready', init);
  window.VLStudio = { runJob, openEditor };
})();
