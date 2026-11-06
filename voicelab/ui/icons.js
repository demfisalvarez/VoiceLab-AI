/* Iconos SVG propios (trazo de 24×24). */
(function () {
  const P = {
    home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20h14V9.5"/><path d="M10 20v-6h4v6"/>',
    waves: '<path d="M2 12h2.5l2-5 3 10 3-14 3 16 3-10 1.5 3H22"/>',
    library: '<rect x="3" y="4" width="4" height="16" rx="1"/><rect x="9" y="4" width="4" height="16" rx="1"/><path d="m15 5.2 3.8-1.1 3.6 14.6-3.8 1.1z"/>',
    voice: '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0"/><path d="M18.5 7.5a3.5 3.5 0 0 1 0 5"/><path d="M21 5a7 7 0 0 1 0 10"/>',
    record: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5" fill="currentColor"/>',
    tts: '<path d="M3 7V5h11v2"/><path d="M8.5 5v14"/><path d="M6 19h5"/><path d="M17 9.5a3.5 3.5 0 0 1 0 5"/><path d="M19.5 7a7 7 0 0 1 0 10"/>',
    editor: '<path d="M3 12h1"/><path d="M6.5 8v8"/><path d="M10 4v16"/><path d="M13.5 9v6"/><path d="M17 6v12"/><path d="M20.5 10v4"/>',
    sliders: '<path d="M4 6h9"/><path d="M19 6h1"/><path d="M4 12h3"/><path d="M13 12h7"/><path d="M4 18h11"/><path d="M21 18h-0"/><circle cx="16" cy="6" r="2.5"/><circle cx="10" cy="12" r="2.5"/><circle cx="18" cy="18" r="2.5"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18"/><path d="M12 3a14 14 0 0 0 0 18"/>',
    power: '<path d="M12 3v8"/><path d="M6.6 6.6a8 8 0 1 0 10.8 0"/>',
    chevron: '<path d="m9 6 6 6-6 6"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    alert: '<path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.5h.01"/>',
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/>',
    sparkles: '<path d="M11 3.5 12.7 8l4.5 1.7-4.5 1.7L11 16l-1.7-4.6L4.8 9.7 9.3 8z"/><path d="M18.5 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
    route: '<circle cx="5" cy="12" r="2"/><path d="M7 12h4"/><path d="M11 12c3 0 3-6 6-6h2"/><path d="M11 12c3 0 3 6 6 6h2"/><path d="M11 12h8"/>',
    plug: '<path d="M9 2.5V7"/><path d="M15 2.5V7"/><path d="M6.5 7h11v3.5a5.5 5.5 0 0 1-11 0z"/><path d="M12 16v5.5"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.4-4.6L4 8"/><path d="M4 3.5V8h4.5"/><path d="M4 13a8 8 0 0 0 14.4 4.6L20 16"/><path d="M20 20.5V16h-4.5"/>',
    external: '<path d="M14 4h6v6"/><path d="M10 14 20 4"/><path d="M19 13.5V19a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5.5"/>',
    gauge: '<path d="M4.5 18a9 9 0 1 1 15 0"/><path d="m12 14 4-5"/><circle cx="12" cy="14" r="1.5"/>',
    headphones: '<path d="M3.5 15v-3a8.5 8.5 0 0 1 17 0v3"/><rect x="3" y="14" width="4.5" height="7" rx="1.6"/><rect x="16.5" y="14" width="4.5" height="7" rx="1.6"/>',
    speaker: '<path d="M4 9.5h3.5L12.5 5v14l-5-4.5H4z"/><path d="M16 9a4.5 4.5 0 0 1 0 6"/><path d="M18.8 6.2a8.5 8.5 0 0 1 0 11.6"/>',
    phone: '<rect x="7" y="2.5" width="10" height="19" rx="2.2"/><path d="M11 18h2"/>',
    play: '<path d="M7 4.5v15l12.5-7.5z"/>',
    gpu: '<rect x="2.5" y="6" width="19" height="12" rx="2"/><circle cx="9" cy="12" r="3"/><path d="M15 10h3.5M15 14h3.5"/>',
    ram: '<rect x="3" y="7" width="18" height="10" rx="1.5"/><path d="M7 10.5v3M11 10.5v3M15 10.5v3"/><path d="M6 17v2M18 17v2"/>',
    windows: '<rect x="3.5" y="3.5" width="17" height="17" rx="2"/><path d="M3.5 12h17M12 3.5v17"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    star: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    trash: '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    download: '<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/>',
    upload: '<path d="M12 20V9"/><path d="m7 14 5-5 5 5"/><path d="M5 4h14"/>',
    archive: '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10h14V9"/><path d="M10 13h4"/>',
    folder: '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8.5A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"/>',
    gate: '<path d="M3.5 5h17l-6.5 7.5V19l-4 2v-8.5z"/>',
  };
  const NS = 'http://www.w3.org/2000/svg';
  window.icon = function (name, cls) {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('class', 'i' + (cls ? ' ' + cls : ''));
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = P[name] || P.info;
    return svg;
  };
  window.iconHTML = function (name, cls) {
    return '<svg viewBox="0 0 24 24" class="i' + (cls ? ' ' + cls : '') + '" aria-hidden="true">' + (P[name] || P.info) + '</svg>';
  };
  window.hydrateIcons = function (root) {
    (root || document).querySelectorAll('i[data-icon]').forEach((el) => {
      el.replaceWith(window.icon(el.dataset.icon, el.className));
    });
  };
})();
