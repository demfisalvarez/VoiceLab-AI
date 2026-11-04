/* Fase 2: panel de efectos, preajustes y perfil activo. */
(function () {
  'use strict';
  let VL, $, schema = null, presets = [], eqFreqs = [], profiles = [];
  const timers = {}, pending = {};

  const GROUPS = [
    { title: 'Tono y timbre', icon: 'voice', items: [['pitch', 'Tono (pitch)', 'st', 0.5], ['formant', 'Formantes', 'st', 0.5], ['robot', 'Voz robótica', 'switch']] },
    { title: 'Limpieza y filtros', icon: 'gate', items: [['noise_reduction', 'Reducción de ruido', '%', 1], ['hpf_enabled', 'Filtro pasaaltos', 'switch'], ['hpf_hz', 'Corte del pasaaltos', 'Hz', 10], ['lpf_enabled', 'Filtro pasabajos', 'switch'], ['lpf_hz', 'Corte del pasabajos', 'Hz', 100]] },
    { title: 'Graves, medios y agudos', icon: 'sliders', items: [['bass', 'Graves', 'dB', 0.5], ['mid', 'Medios', 'dB', 0.5], ['treble', 'Agudos', 'dB', 0.5]] },
    { title: 'Ecualizador gráfico', icon: 'editor', eq: true },
    { title: 'Dinámica', icon: 'gauge', items: [['comp_enabled', 'Compresor', 'switch'], ['comp_threshold', 'Umbral', 'dB', 1], ['comp_ratio', 'Relación', ':1', 0.5], ['comp_makeup', 'Compensación', 'dB', 0.5], ['limiter_enabled', 'Limitador', 'switch'], ['limiter_ceiling', 'Techo', 'dB', 0.5], ['gain', 'Ganancia de salida', 'dB', 0.5]] },
    { title: 'Color', icon: 'sparkles', items: [['saturation', 'Saturación', '%', 1], ['distortion', 'Distorsión', '%', 1], ['lofi', 'Lo-fi (8 bits)', '%', 1], ['ring_hz', 'Modulación en anillo', 'Hz', 5], ['ring_mix', 'Mezcla del anillo', '%', 1]] },
    { title: 'Espacio', icon: 'waves', items: [['chorus_mix', 'Chorus', '%', 1], ['chorus_rate', 'Velocidad del chorus', 'Hz', 0.1], ['chorus_depth', 'Profundidad del chorus', 'ms', 0.5], ['echo_mix', 'Eco', '%', 1], ['echo_delay', 'Retardo del eco', 'ms', 10], ['echo_feedback', 'Repeticiones del eco', '%', 1], ['reverb_mix', 'Reverberación', '%', 1], ['reverb_size', 'Tamaño de la sala', '%', 1], ['reverb_damping', 'Amortiguación', '%', 1]] },
  ];

  const params = () => VL.S.settings.voice.params;
  const fmtFreq = (f) => (f >= 1000 ? (f / 1000) + 'k' : String(f));

  function rangeRow(key, label, unit, step) {
    const sc = schema[key];
    return '<div class="fx-row"><div class="field-label">' + VL.esc(label) + '</div>' +
      '<div class="range-field" data-fx="' + key + '"><input type="range" min="' + sc.min + '" max="' + sc.max + '" step="' + step + '">' +
      '<input type="number" min="' + sc.min + '" max="' + sc.max + '" step="' + step + '"><span class="unit">' + VL.esc(unit) + '</span></div></div>';
  }
  function switchRow(key, label) {
    return '<div class="fx-row fx-switch"><div class="field-label">' + VL.esc(label) + '</div><button class="switch" role="switch" data-fxs="' + key + '" aria-label="' + VL.esc(label) + '"></button></div>';
  }

  function build() {
    $('#presets').innerHTML = '<button class="preset" data-preset="">Voz original</button>' +
      presets.map((p) => '<button class="preset" data-preset="' + p.id + '">' + VL.esc(p.label) + '</button>').join('');
    $('#fx-grid').innerHTML = GROUPS.map((g) => {
      let body;
      if (g.eq) {
        body = '<div class="eq">' + eqFreqs.map((f, i) =>
          '<div class="eq-band" data-fx="eq' + i + '"><input type="number" min="-12" max="12" step="0.5" aria-label="' + fmtFreq(f) + ' Hz">' +
          '<input type="range" min="-12" max="12" step="0.5" aria-label="Banda ' + fmtFreq(f) + ' Hz"><span>' + fmtFreq(f) + '</span></div>').join('') + '</div>';
      } else {
        body = g.items.map((it) => (it[2] === 'switch' ? switchRow(it[0], it[1]) : rangeRow(it[0], it[1], it[2], it[3]))).join('');
      }
      return '<details class="fx-group' + (g.eq ? ' wide' : '') + '" open><summary>' + iconHTML(g.icon) + '<span>' + VL.esc(g.title) + '</span><span class="fx-dot"></span></summary><div class="fx-body">' + body + '</div></details>';
    }).join('');

    VL.$$('[data-fx]').forEach((el) => {
      const key = el.dataset.fx;
      const inputs = el.querySelectorAll('input');
      const range = el.querySelector('input[type=range]'), num = el.querySelector('input[type=number]');
      const paint = (v) => { const sc = schema[key]; range.style.setProperty('--pct', ((v - sc.min) / (sc.max - sc.min) * 100) + '%'); };
      el._set = (v) => { range.value = v; num.value = v; paint(v); };
      inputs.forEach((inp) => inp.addEventListener(inp.type === 'range' ? 'input' : 'change', () => {
        const sc = schema[key];
        let v = parseFloat(inp.value);
        if (isNaN(v)) v = params()[key];
        v = Math.min(sc.max, Math.max(sc.min, v));
        el._set(v);
        queue(key, v);
      }));
    });
    VL.$$('[data-fxs]').forEach((el) => el.addEventListener('click', () => {
      const v = el.getAttribute('aria-checked') !== 'true';
      el.setAttribute('aria-checked', String(v));
      queue(el.dataset.fxs, v, true);
    }));
    VL.$$('[data-preset]').forEach((b) => b.addEventListener('click', async () => {
      const id = b.dataset.preset;
      VL.applyResponse(await VL.call(id ? 'apply_preset' : 'reset_voice', ...(id ? [id] : [])));
      render();
    }));
  }

  function queue(key, value, now) {
    pending[key] = value;
    if (timers.t) return;
    timers.t = setTimeout(flush, now ? 0 : 60);
  }
  async function flush() {
    timers.t = null;
    const patch = Object.assign({}, pending);
    for (const k in pending) delete pending[k];
    const res = await VL.call('set_voice_params', patch);
    VL.applyResponse(res);
    renderLabels();
  }

  function render() {
    if (!schema || !VL.S.settings) return;
    const p = params();
    VL.$$('[data-fx]').forEach((el) => { if (el._set && !(el.dataset.fx in pending)) el._set(p[el.dataset.fx]); });
    VL.$$('[data-fxs]').forEach((el) => el.setAttribute('aria-checked', String(!!p[el.dataset.fxs])));
    renderLabels();
  }

  function same(a, b) { return Object.keys(schema).every((k) => a[k] === b[k]); }

  function renderLabels() {
    const v = VL.S.settings.voice, p = v.params;
    const defaults = {};
    Object.keys(schema).forEach((k) => { defaults[k] = schema[k].default; });
    const prof = profiles.find((x) => x.id === v.profile_id);
    const preset = presets.find((x) => x.id === v.preset);
    let name;
    if (prof) name = prof.name + (same(prof.effects, p) ? '' : ' · modificado');
    else if (preset) name = preset.label + (same(preset.params, p) ? '' : ' · modificado');
    else name = same(defaults, p) ? 'Voz original' : 'Ajustes personalizados';
    $('#voice-name').textContent = name;
    $('#voice-save-current').hidden = !(prof && !same(prof.effects, p));
    VL.$$('[data-preset]').forEach((b) => b.classList.toggle('active', b.dataset.preset === (v.preset || (same(defaults, p) && !prof ? '' : '__'))));
    VL.$$('.fx-group').forEach((g) => {
      const active = [...g.querySelectorAll('[data-fx],[data-fxs]')].some((el) => {
        const k = el.dataset.fx || el.dataset.fxs;
        return p[k] !== schema[k].default && !/_hz$|_rate$|_depth$|_delay$|_feedback$|_size$|_damping$|_threshold$|_ratio$|_ceiling$/.test(k);
      });
      g.querySelector('.fx-dot').classList.toggle('on', active);
    });
    const sel = $('#profile-quick');
    sel.innerHTML = '<option value="">— Sin perfil (ajustes actuales) —</option>' +
      profiles.map((x) => '<option value="' + x.id + '"' + (x.id === v.profile_id ? ' selected' : '') + '>' + VL.esc(x.name) + ' · ' + VL.esc(x.type_label) + '</option>').join('');
  }

  async function loadProfiles() {
    const r = await VL.call('list_profiles');
    if (r.ok) profiles = r.profiles;
    renderLabels();
  }

  async function init() {
    VL = window.VL; $ = VL.$;
    const r = await VL.call('get_effects_schema');
    if (!r.ok) return;
    schema = r.schema; presets = r.presets; eqFreqs = r.eq_freqs;
    build();
    await loadProfiles();
    render();
    $('#profile-quick').addEventListener('change', async (e) => {
      const id = e.target.value;
      if (id) VL.applyResponse(await VL.call('activate_profile', id));
      else VL.applyResponse(await VL.call('update_settings', { voice: { profile_id: null } }));
      render();
    });
    $('#voice-reset').addEventListener('click', async () => { VL.applyResponse(await VL.call('reset_voice')); render(); });
    $('#voice-save-current').addEventListener('click', async () => {
      const r2 = VL.applyResponse(await VL.call('save_voice_to_profile', VL.S.settings.voice.profile_id));
      if (r2.ok) { VL.toast('ok', 'Perfil actualizado.'); await loadProfiles(); }
    });
    $('#voice-save-new').addEventListener('click', async () => {
      const data = await VL.profileModal({ title: 'Guardar como perfil nuevo' });
      if (!data) return;
      const c = await VL.call('create_profile', { name: data.name, folder: data.folder, description: data.description });
      if (!c.ok) { VL.toast('err', c.error); return; }
      if (data.avatar) await VL.call('set_profile_avatar', c.result.id, data.avatar);
      VL.applyResponse(await VL.call('update_settings', { voice: { profile_id: c.result.id, preset: null } }));
      VL.toast('ok', 'Perfil «' + c.result.name + '» guardado en la biblioteca.');
      await loadProfiles();
      document.dispatchEvent(new CustomEvent('vl:profiles'));
    });
    document.addEventListener('vl:profiles', loadProfiles);
  }

  document.addEventListener('vl:ready', init);
  document.addEventListener('vl:settings', () => { if (schema) render(); });
  window.VLVoice = { reloadProfiles: () => loadProfiles() };
})();
