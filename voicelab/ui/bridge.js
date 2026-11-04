/* Puente entre la interfaz y el motor en Python.
 * - Ventana nativa: window.pywebview.api (inyectado por pywebview).
 * - Modo navegador: POST /api/<función> con un token de sesión.
 */
(function () {
  const params = new URLSearchParams(location.search);
  let token = params.get('token');
  try {
    if (token) {
      sessionStorage.setItem('voicelab-token', token);
      history.replaceState(null, '', location.pathname);
    } else {
      token = sessionStorage.getItem('voicelab-token');
    }
  } catch (e) { /* almacenamiento no disponible: se mantiene en memoria */ }

  // En un arranque en frío (WebView2 + .NET + Python) el puente de pywebview
  // puede tardar bastante más de unos segundos: se espera hasta que exista de
  // verdad (evento + sondeo) en lugar de rendirse antes de tiempo.
  const ready = () => !!(window.pywebview && window.pywebview.api && window.pywebview.api.get_initial_state);
  const mode = new Promise((resolve) => {
    if (token) return resolve('http');
    if (ready()) return resolve('webview');
    const t0 = Date.now();
    const done = (m) => { clearInterval(timer); resolve(m); };
    window.addEventListener('pywebviewready', () => { if (ready()) done('webview'); }, { once: true });
    const timer = setInterval(() => {
      if (ready()) done('webview');
      else if (Date.now() - t0 > 8000) {
        const msg = document.getElementById('boot-msg');
        if (msg) msg.textContent = 'Iniciando el motor de audio… (la primera vez tras encender el PC puede tardar un poco)';
      }
      if (Date.now() - t0 > 120000) done('none');
    }, 100);
  });

  async function call(name, ...args) {
    const m = await mode;
    try {
      if (m === 'webview') {
        const fn = window.pywebview.api[name];
        if (!fn) return { ok: false, error: 'Función no disponible: ' + name };
        return await fn(...args);
      }
      if (m === 'http') {
        const res = await fetch('/api/' + name, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-VoiceLab-Token': token },
          body: JSON.stringify({ args }),
        });
        return await res.json();
      }
      return { ok: false, error: 'No hay conexión con el motor de VoiceLab AI.' };
    } catch (err) {
      return { ok: false, error: 'Sin respuesta del motor de audio (' + (err && err.message || err) + ').' };
    }
  }

  if (token) {
    window.addEventListener('pagehide', () => {
      try { navigator.sendBeacon('/api/__closing?token=' + encodeURIComponent(token)); } catch (e) {}
    });
  }

  window.Bridge = { call, mode };
})();
