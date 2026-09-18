/* Shared navigation for the integrated local prototype. */
(() => {
  const embedded = window.parent !== window;
  if (!embedded && !document.body.classList.contains('career-host')) {
    const url = new URL(location.href); url.searchParams.delete('embed');
    location.replace('/#' + url.pathname + url.search); return;
  }
  if (embedded) {
    document.body.classList.add('career-embedded');
    const tellLocation = () => parent.postMessage({ type: 'career-location', path: location.pathname + location.search, title: document.title }, location.origin);
    document.addEventListener('click', e => {
      const a = e.target.closest('a[href]'); if (!a || a.target === '_blank' || a.download || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      const url = new URL(a.href); if (url.origin !== location.origin || !/^\/(today|profile|market|editor)(\/|$)/.test(url.pathname)) return;
      e.preventDefault(); e.stopImmediatePropagation(); parent.postMessage({ type: 'career-open', path: url.pathname + url.search }, location.origin);
    }, true);
    window.addEventListener('message', e => {
      if (e.source !== parent || e.origin !== location.origin || e.data?.type !== 'career-navigate') return;
      const url = new URL(e.data.path, location.origin);
      if (url.pathname.startsWith('/market/') && typeof render === 'function') {
        const target = url.searchParams.get('view') || 'market';
        if (target === 'market' || target === 'applications') {
          const b = document.createElement('button'); b.hidden = true; b.dataset.view = target; document.body.append(b); b.click(); b.remove();
        }
      }
      tellLocation();
    });
    const content = document.querySelector('main#app');
    if (content) new MutationObserver(tellLocation).observe(content, { childList: true });
    window.addEventListener('load', () => parent.postMessage({ type: 'career-ready' }, location.origin), { once: true });
    // Scripts loaded after the document load can still announce readiness.
    if (document.readyState === 'complete') parent.postMessage({ type: 'career-ready' }, location.origin);
  }
  const routes = [
    ['today', 'Today', '/today/', '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>'],
    ['profile', '个人资料', '/profile/', '<circle cx="12" cy="7" r="4"/><path d="M5 21v-3a7 7 0 0 1 14 0v3"/>'],
    ['market', '岗位市场', '/market/index.html', '<rect x="3" y="7" width="18" height="14" rx="3"/><path d="M8 7V4h8v3M3 12q9 6 18 0M10 13h4"/>'],
    ['applications', '我的投递', '/market/index.html?view=applications', '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h1m3 0h3M9 12h7M9 16h7"/>'],
    ['practice', '个人练习场', null, '<path d="M9 15 4 20l1-6 9-10 6-1-1 6-10 9zM14 5l5 5"/>'],
    ['offers', 'Offer 池', null, '<path d="m12 3 9 9-9 9-9-9z"/>'],
    ['community', '面经社区', null, '<path d="M4 4h16v14H10l-5 3v-3H4zM8 10h.1M12 10h.1M16 10h.1"/>'],
    ['plugins', '插件市场', null, '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>']
  ];
  const sidebar = document.querySelector('.sidebar,.pp-side,.ct-side');
  document.body.classList.add('career-unified');
  if (!sidebar) return; // The resume editor keeps its document-focused layout.
  sidebar.classList.add('career-sidebar');
  const brand = sidebar.querySelector('.brand,.pp-brand,.ct-brand');
  brand.className = 'career-brand';
  brand.innerHTML = '<span class="career-mark">✦</span><span>career os<small>让好机会触手可及</small></span>';
  const nav = sidebar.querySelector('nav');
  nav.className = 'career-nav';
  nav.setAttribute('aria-label', '主导航');
  nav.innerHTML = routes.map(([key, label, href, path]) => {
    const icon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
    return href ? `<a data-route="${key}" href="${href}" aria-label="${label}">${icon}<span>${label}</span></a>` : `<span class="career-pending" aria-disabled="true" aria-label="${label} · 待开放" title="${label} · 待开放">${icon}<span>${label}</span><small>待开放</small></span>`;
  }).join('');
  function sync() {
    const key = document.querySelector('#career-today') ? 'today' : document.querySelector('#career-profile') ? 'profile' : document.body.classList.contains('market-view') ? 'market' : 'applications';
    nav.querySelectorAll('a').forEach(a => {
      const active = a.dataset.route === key;
      a.classList.toggle('active', active);
      if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    const title = document.querySelector('#app > .top h1');
    if (title) document.title = `Career OS · ${title.textContent}`;
  }
  sync();
  new MutationObserver(sync).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  const app = document.querySelector('main#app');
  if (app) new MutationObserver(sync).observe(app, { childList: true });
  const todayHeader = document.querySelector('.ct-topbar');
  if (todayHeader) todayHeader.innerHTML = '<div><h1>Today</h1><p>你的求职日常，从这里开始。</p></div><span class="ct-prototype">交互预览 · 示例数据</span>';
})();
