/* VoiceLab AI — idiomas de la interfaz.
 *
 * La interfaz se escribe en español y este archivo la traduce en el propio
 * navegador: los diccionarios de locales/<idioma>.js usan como clave el texto
 * original. Se traducen los nodos de texto y los atributos visibles
 * (title, placeholder, aria-label, alt) al arrancar y cada vez que la app
 * cambia el DOM (MutationObserver), y los diálogos nativos (confirm/prompt/alert).
 *
 * Las claves con {} son patrones: «Cálculo {} ms por bloque de {} ms» reconoce
 * el texto con cualquier valor y lo coloca en la traducción ({} en orden, o
 * {1}, {2}… para cambiar el orden). Lo que va dentro de cada {} también se
 * traduce si está en el diccionario (por ejemplo, un error que llega de Python).
 *
 * El idioma se elige en Ajustes (ui.language) y se recuerda en localStorage
 * para aplicarlo antes de pintar la ventana. «auto» usa el idioma de Windows.
 */
(function () {
  'use strict';

  const SUPPORTED = ['es', 'en', 'fr', 'it', 'pt', 'ru', 'zh', 'ja'];
  const NAMES = {
    es: 'Español', en: 'English', fr: 'Français', it: 'Italiano',
    pt: 'Português', ru: 'Русский', zh: '中文（简体）', ja: '日本語',
  };
  const STORE = 'vl-lang';
  const ATTRS = ['title', 'placeholder', 'aria-label', 'alt'];
  const LETTER = /[A-Za-zÁÉÍÓÚÜáéíóúüñÑ]/;

  function pick(v) {
    const base = String(v || '').toLowerCase().split(/[-_]/)[0];
    return SUPPORTED.indexOf(base) >= 0 ? base : null;
  }

  // Idioma que corresponde a una preferencia («auto» o un código).
  function resolve(pref) {
    if (pref && pref !== 'auto' && pick(pref)) return pick(pref);
    const list = (navigator.languages && navigator.languages.length) ? navigator.languages : [navigator.language];
    for (const l of list) { const p = pick(l); if (p) return p; }
    return 'en';
  }

  let pref = null, forced = false;
  try { pref = localStorage.getItem(STORE); } catch (e) { /* almacenamiento no disponible */ }
  try {
    const q = new URLSearchParams(location.search).get('lang');   // ?lang=xx (pruebas)
    if (q) { pref = q; forced = true; }
  } catch (e) { /* sin parámetros */ }
  const lang = resolve(pref);

  // ------------------------------------------------------------ diccionario
  let exact = null;          // Map texto → traducción
  let patterns = [];         // [{re, out}]
  const cache = new Map();

  function compile(dict) {
    exact = new Map();
    patterns = [];
    for (const k of Object.keys(dict)) {
      const v = dict[k];
      if (typeof v !== 'string' || !v) continue;
      if (k.indexOf('{}') < 0) { exact.set(k, v); continue; }
      const parts = k.split('{}').map(p => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/ /g, '\\s+'));
      patterns.push({ re: new RegExp('^' + parts.join('([\\s\\S]*?)') + '$'), out: v, weight: k.replace(/\{\}/g, '').length });
    }
    patterns.sort((a, b) => b.weight - a.weight);   // los más concretos primero
    cache.clear();
  }

  function fill(out, args) {
    let n = 0;
    return out.replace(/\{(\d*)\}/g, (m, i) => {
      const a = i ? args[Number(i) - 1] : args[n++];
      return a === undefined ? '' : a;
    });
  }

  function lookup(text, depth) {
    let r = exact.get(text);
    if (r !== undefined) return r;
    if (depth > 2) return null;
    for (const p of patterns) {
      const m = p.re.exec(text);
      if (!m) continue;
      const args = m.slice(1).map(a => {
        const lead = a.match(/^\s*/)[0], trail = a.match(/\s*$/)[0];
        const core = a.trim();
        const tr = core && LETTER.test(core) ? part(core, depth + 1) : null;
        return tr == null ? a : lead + tr + trail;
      });
      return fill(p.out, args);
    }
    return null;
  }

  // Lo que va dentro de un {}: además de la búsqueda normal, prueba sin la
  // mayúscula inicial («El micrófono» → «el micrófono») y separando un nombre
  // final entre comillas («el micrófono «USB»» → traduce «el micrófono»).
  function part(text, depth) {
    let r = lookup(text, depth);
    if (r != null) return r;
    const first = text.charAt(0);
    if (first !== first.toLowerCase()) {
      r = lookup(first.toLowerCase() + text.slice(1), depth);
      if (r != null) return r.charAt(0).toUpperCase() + r.slice(1);
    }
    const q = /^(.+?)\s+(«[^»]*»)$/.exec(text);
    if (q) {
      const head = part(q[1], depth);
      if (head != null) return head + ' ' + q[2];
    }
    return null;
  }

  // Traduce un texto; devuelve el original si no está en el diccionario.
  function t(s) {
    if (!exact || s == null) return s;
    s = String(s);
    if (!LETTER.test(s)) return s;
    if (cache.has(s)) { const c = cache.get(s); return c == null ? s : c; }
    let out = null;
    const raw = exact.get(s.trim());
    if (raw !== undefined) {
      out = s.match(/^\s*/)[0] + raw + s.match(/\s*$/)[0];
    } else {
      const lead = s.match(/^\s*/)[0], trail = s.match(/\s*$/)[0];
      const core = s.trim().replace(/\s+/g, ' ');
      let r = core ? lookup(core, 0) : null;
      if (r == null && /[.:]$/.test(core)) {        // «… o más.» cuando la clave no lleva el punto
        const r2 = lookup(core.slice(0, -1), 0);
        const end = core.slice(-1), cjk = lang === 'zh' || lang === 'ja';
        if (r2 != null) r = r2 + (/[。．：.:]$/.test(r2) ? '' : cjk ? (end === '.' ? '。' : '：') : end);
      }
      if (r != null) out = lead + r + trail;
    }
    if (cache.size > 6000) cache.clear();
    cache.set(s, out);
    return out == null ? s : out;
  }

  // ------------------------------------------------------------ DOM
  // Sin traducir el contenido (el texto del usuario) …
  const SKIP = 'script,style,textarea,code,pre,svg,[translate="no"],[contenteditable="true"]';
  // … y sin traducir tampoco los atributos.
  const SKIP_ATTR = 'script,style,svg,[translate="no"]';
  const doneText = new WeakMap();      // nodo de texto → texto traducido que pusimos
  const doneAttr = new WeakMap();      // elemento → {atributo: valor traducido}

  function skipped(el) {
    return !el || (el.closest && el.closest(SKIP));
  }

  function doText(node) {
    const v = node.data;
    if (doneText.get(node) === v) return;
    const tr = t(v);
    if (tr !== v) { doneText.set(node, tr); node.data = tr; } else doneText.set(node, v);
  }

  function doAttrs(el) {
    if (!el.getAttribute) return;
    for (const a of ATTRS) {
      const v = el.getAttribute(a);
      if (!v) continue;
      const seen = doneAttr.get(el);
      if (seen && seen[a] === v) continue;
      const tr = t(v);
      const rec = seen || {};
      rec[a] = tr;
      doneAttr.set(el, rec);
      if (tr !== v) el.setAttribute(a, tr);
    }
  }

  function walk(root) {
    if (root.nodeType === 3) {
      if (!skipped(root.parentElement)) doText(root);
      return;
    }
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    if (root.nodeType === 1 && skipped(root)) {
      if (!root.closest(SKIP_ATTR)) doAttrs(root);
      return;
    }
    if (root.nodeType === 1) doAttrs(root);
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        if (n.nodeType === 1 && n.matches(SKIP)) {
          if (!n.matches(SKIP_ATTR)) doAttrs(n);     // placeholder de un textarea, por ejemplo
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    let n;
    while ((n = tw.nextNode())) {
      if (n.nodeType === 3) doText(n); else doAttrs(n);
    }
  }

  function observe() {
    const mo = new MutationObserver(list => {
      for (const m of list) {
        if (m.type === 'childList') {
          m.addedNodes.forEach(walk);
        } else if (m.type === 'characterData') {
          if (!skipped(m.target.parentElement)) doText(m.target);
        } else if (m.type === 'attributes') {
          if (!m.target.closest(SKIP_ATTR)) doAttrs(m.target);
        }
      }
    });
    mo.observe(document.documentElement, {
      childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS,
    });
  }

  // ------------------------------------------------------------ diálogos nativos
  function wrapDialogs() {
    const c = window.confirm, p = window.prompt, a = window.alert;
    window.confirm = m => c.call(window, t(m));
    window.prompt = (m, d) => p.call(window, t(m), d);
    window.alert = m => a.call(window, t(m));
  }

  const api = {
    lang, pref: pref || 'auto', forced, names: NAMES, supported: SUPPORTED, t, resolve,
    register(code, dict) {
      if (code !== lang) return;
      compile(dict);
    },
    // Guarda la preferencia para el próximo arranque; devuelve true si cambia el idioma.
    remember(p) {
      try { localStorage.setItem(STORE, p || 'auto'); } catch (e) { return false; }
      return resolve(p) !== lang;
    },
  };
  window.VL_I18N = api;

  document.documentElement.lang = lang;
  if (lang !== 'es') {
    // Se oculta la ventana hasta traducirla para no ver el español un instante.
    document.documentElement.style.visibility = 'hidden';
    document.write('<script src="locales/' + lang + '.js"><\/script>');
    const show = () => { document.documentElement.style.visibility = ''; };
    setTimeout(show, 1500);   // por si faltara el diccionario
    document.addEventListener('DOMContentLoaded', () => {
      if (exact) {
        wrapDialogs();
        walk(document.documentElement);
        observe();
      }
      show();
    });
  }
})();
