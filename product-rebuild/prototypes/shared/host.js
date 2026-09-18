(() => {
  const area = document.querySelector('#page-content'), status = document.querySelector('#host-status');
  const frames = new Map(); let active = null;
  function route(path) {
    const url = new URL(path || '/today/', location.origin);
    if (url.origin !== location.origin || !/^\/(today|profile|market|editor)(\/|$)/.test(url.pathname)) return null;
    url.searchParams.delete('embed'); return url.pathname + url.search;
  }
  function highlight(path) {
    const key = path.startsWith('/today') ? 'today' : /^\/(profile|editor)/.test(path) ? 'profile' : /view=(applications|workspace)/.test(path) ? 'applications' : 'market';
    document.querySelectorAll('[data-route]').forEach(a => { const selected = a.dataset.route === key; a.classList.toggle('active', selected); if (selected) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  }
  function show(entry) {
    if (entry !== active || !entry.ready) return;
    for (const other of frames.values()) other.frame.hidden = other !== entry;
    status.hidden = true;
  }
  function navigate(raw, historyMode = 'push') {
    const path = route(raw); if (!path) return;
    const key = path.split('/')[1];
    if (historyMode === 'push' && location.hash !== '#' + path) history.pushState(null, '', '#' + path);
    highlight(path);
    let entry = frames.get(key);
    // An explicit new resume must consume the newly supplied profile seed.
    if (entry && key === 'editor' && sessionStorage.getItem('career-resume-seed')) {
      entry.frame.remove(); frames.delete(key); entry = null;
    }
    if (!entry) {
      const frame = document.createElement('iframe'); frame.title = 'Career OS 页面'; frame.hidden = true;
      entry = { frame, ready: false, path }; frames.set(key, entry); active = entry;
      const url = new URL(path, location.origin); url.searchParams.set('embed', '1'); frame.src = url;
      area.append(frame);
    } else {
      active = entry; entry.path = path;
      if (entry.ready) entry.frame.contentWindow.postMessage({ type: 'career-navigate', path }, location.origin);
    }
    if (!entry.ready) { status.hidden = false; status.textContent = '正在打开页面…'; }
    show(entry);
  }
  document.addEventListener('click', e => {
    const a = e.target.closest('a[data-route]');
    if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault(); navigate(a.getAttribute('href'));
  });
  window.addEventListener('message', e => {
    if (e.origin !== location.origin) return;
    const entry = [...frames.values()].find(x => x.frame.contentWindow === e.source); if (!entry) return;
    if (e.data?.type === 'career-ready') {
      entry.ready = true;
      if (entry === active) { entry.frame.contentWindow.postMessage({ type: 'career-navigate', path: entry.path }, location.origin); show(entry); }
    }
    if (e.data?.type === 'career-open' && entry === active) navigate(e.data.path);
    if (e.data?.type === 'career-location' && entry === active) {
      const path = route(e.data.path); if (!path) return;
      entry.path = path; history.replaceState(null, '', '#' + path); highlight(path); document.title = e.data.title || 'Career OS';
    }
  });
  window.addEventListener('popstate', () => navigate(location.hash.slice(1), 'none'));
  navigate(location.hash.slice(1) || '/today/', 'none');
})();
