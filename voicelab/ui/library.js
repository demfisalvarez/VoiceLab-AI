/* Biblioteca de voces: buscar, organizar, editar, duplicar, exportar, importar y copias. */
(function () {
  'use strict';
  let VL, $, profiles = [], folders = [];

  // --------------------------------------------------- diálogo de perfil
  function profileModal(opts) {
    const m = $('#pmodal');
    $('#pmodal-title').textContent = opts.title || 'Perfil';
    $('#pm-name').value = opts.name || '';
    $('#pm-folder').value = opts.folder || '';
    $('#pm-desc').value = opts.description || '';
    $('#pm-folders').innerHTML = folders.map((f) => '<option value="' + VL.esc(f) + '">').join('');
    const img = $('#pm-avatar');
    let avatar = null;
    img.src = opts.avatar || 'assets/logo.svg';
    const file = $('#pm-avatar-file');
    file.value = '';
    file.onchange = () => {
      const f = file.files[0];
      if (!f) return;
      if (f.size > 3 * 1024 * 1024) { VL.toast('err', 'La imagen supera 3 MB.'); return; }
      const rd = new FileReader();
      rd.onload = () => { avatar = rd.result; img.src = avatar; };
      rd.readAsDataURL(f);
    };
    m.classList.add('open');
    setTimeout(() => $('#pm-name').focus(), 50);
    return new Promise((resolve) => {
      const done = (ok) => {
        if (ok && !$('#pm-name').value.trim()) { VL.toast('err', 'Escribe un nombre para el perfil.'); return; }
        m.classList.remove('open');
        $('#pm-ok').onclick = $('#pm-cancel').onclick = null;
        resolve(ok ? { name: $('#pm-name').value.trim(), folder: $('#pm-folder').value.trim(), description: $('#pm-desc').value.trim(), avatar } : null);
      };
      $('#pm-ok').onclick = () => done(true);
      $('#pm-cancel').onclick = () => done(false);
    });
  }

  // -------------------------------------------------------------- render
  function initials(name) {
    return VL.esc(name.split(/\s+/).slice(0, 2).map((w) => w[0] || '').join('').toUpperCase());
  }

  function render() {
    const q = $('#lib-search').value.trim().toLowerCase();
    const folder = $('#lib-folder').value, type = $('#lib-type').value;
    const active = VL.S.settings && VL.S.settings.voice.profile_id;
    const fsel = $('#lib-folder');
    const cur = fsel.value;
    fsel.innerHTML = '<option value="">Todas las carpetas</option>' + folders.map((f) => '<option' + (f === cur ? ' selected' : '') + '>' + VL.esc(f) + '</option>').join('');
    const list = profiles.filter((p) => (!q || (p.name + ' ' + (p.description || '') + ' ' + (p.folder || '')).toLowerCase().includes(q)) &&
      (!folder || p.folder === folder) && (!type || p.type === type));
    const grid = $('#lib-grid');
    if (!profiles.length) {
      grid.innerHTML = '<div class="card lib-empty">' + iconHTML('library', 'xl') + '<h3>Todavía no tienes perfiles</h3><p class="muted">Ajusta tu voz en el modulador y pulsa «Guardar como perfil nuevo». Las voces clonadas también aparecerán aquí.</p><button class="btn primary" data-goto="modulator">Ir al modulador</button></div>';
      return;
    }
    if (!list.length) { grid.innerHTML = '<div class="card lib-empty"><p class="muted">Ningún perfil coincide con la búsqueda.</p></div>'; return; }
    grid.innerHTML = list.map((p) =>
      '<div class="card lib-card' + (p.id === active ? ' active' : '') + '" data-id="' + p.id + '">' +
        '<div class="lib-head">' +
          (p.avatar ? '<img class="avatar" src="' + p.avatar + '" alt="">' : '<div class="avatar ph">' + initials(p.name) + '</div>') +
          '<div style="min-width:0;flex:1"><div class="lib-name" title="' + VL.esc(p.name) + '">' + VL.esc(p.name) + '</div>' +
          '<div class="lib-meta"><span class="badge">' + VL.esc(p.type_label) + '</span>' + (p.folder ? '<span>' + iconHTML('folder') + VL.esc(p.folder) + '</span>' : '') + '</div></div>' +
          '<button class="star' + (p.favorite ? ' on' : '') + '" data-act="fav" title="Favorito" aria-label="Favorito">' + iconHTML('star') + '</button>' +
        '</div>' +
        '<p class="lib-desc">' + (p.description ? VL.esc(p.description) : '<span class="muted">Sin descripción</span>') + '</p>' +
        '<div class="lib-date muted small">Creado el ' + new Date(p.created).toLocaleDateString('es-ES', { day: 'numeric', month: 'long', year: 'numeric' }) + (p.has_reference ? ' · con audio de referencia' : '') + '</div>' +
        '<div class="lib-actions">' +
          '<button class="btn sm' + (p.id === active ? '' : ' primary') + '" data-act="use">' + (p.id === active ? 'En uso' : 'Usar') + '</button>' +
          '<button class="btn sm ghost" data-act="edit" title="Editar">' + iconHTML('edit') + '</button>' +
          '<button class="btn sm ghost" data-act="dup" title="Duplicar">' + iconHTML('copy') + '</button>' +
          '<button class="btn sm ghost" data-act="export" title="Exportar">' + iconHTML('upload') + '</button>' +
          '<button class="btn sm ghost" data-act="del" title="Eliminar">' + iconHTML('trash') + '</button>' +
        '</div></div>').join('');
  }

  async function load() {
    const r = await VL.call('list_profiles');
    if (r.ok) { profiles = r.profiles; folders = r.folders; }
    render();
  }

  function afterChange(r) {
    if (!r.ok) { VL.toast('err', r.error); return false; }
    if (r.profiles) { profiles = r.profiles; folders = r.folders; }
    render();
    document.dispatchEvent(new CustomEvent('vl:profiles'));
    return true;
  }

  function pathToast(text, path) {
    VL.toast('ok', text + ' ' + path);
    if (VL.S.app.platform === 'win32') VL.call('reveal_path', path);
  }

  async function onAction(act, id) {
    const p = profiles.find((x) => x.id === id);
    if (!p) return;
    if (act === 'use') { VL.applyResponse(await VL.call('activate_profile', id)); render(); VL.toast('ok', 'Perfil «' + p.name + '» activado.'); }
    else if (act === 'fav') afterChange(await VL.call('update_profile', id, { favorite: !p.favorite }));
    else if (act === 'dup') { if (afterChange(await VL.call('duplicate_profile', id))) VL.toast('ok', 'Perfil duplicado.'); }
    else if (act === 'export') {
      const r = await VL.call('export_profile', id);
      if (r.ok) pathToast('Perfil exportado:', r.path); else VL.toast('err', r.error);
    } else if (act === 'del') {
      if (!window.confirm('¿Eliminar el perfil «' + p.name + '»? Esta acción no se puede deshacer.')) return;
      if (afterChange(await VL.call('delete_profile', id))) VL.toast('ok', 'Perfil eliminado.');
    } else if (act === 'edit') {
      const d = await profileModal({ title: 'Editar perfil', name: p.name, folder: p.folder, description: p.description, avatar: p.avatar });
      if (!d) return;
      if (!afterChange(await VL.call('update_profile', id, { name: d.name, folder: d.folder, description: d.description }))) return;
      if (d.avatar) afterChange(await VL.call('set_profile_avatar', id, d.avatar));
    }
  }

  async function importProfile() {
    const r = await VL.call('import_profile');
    if (r.needs_upload) { $('#lib-import-file').click(); return; }
    if (r.cancelled) return;
    if (afterChange(r)) VL.toast('ok', 'Perfil «' + r.result.name + '» importado.');
  }

  function init() {
    VL = window.VL; $ = VL.$;
    VL.profileModal = profileModal;
    $('#lib-search').addEventListener('input', render);
    $('#lib-folder').addEventListener('change', render);
    $('#lib-type').addEventListener('change', render);
    $('#lib-grid').addEventListener('click', (e) => {
      const b = e.target.closest('[data-act]');
      if (b) onAction(b.dataset.act, b.closest('[data-id]').dataset.id);
    });
    $('#lib-import').addEventListener('click', importProfile);
    $('#lib-import-file').addEventListener('change', () => {
      const f = $('#lib-import-file').files[0];
      if (!f) return;
      const rd = new FileReader();
      rd.onload = async () => {
        const r = await VL.call('import_profile', f.name, rd.result);
        if (afterChange(r)) VL.toast('ok', 'Perfil «' + r.result.name + '» importado.');
        $('#lib-import-file').value = '';
      };
      rd.readAsDataURL(f);
    });
    $('#lib-backup').addEventListener('click', async () => {
      const r = await VL.call('backup_profiles');
      if (r.ok) pathToast('Copia de seguridad creada:', r.path); else VL.toast('err', r.error);
    });
    document.addEventListener('vl:page', (e) => { if (e.detail === 'library') load(); });
    document.addEventListener('vl:profiles', () => { if (VL.S.page === 'library') load(); });
    document.addEventListener('vl:settings', () => { if (VL.S.page === 'library') render(); });
    load();
  }

  // Se registra antes que voice.js para que profileModal exista cuando haga falta.
  document.addEventListener('vl:ready', init);
})();
