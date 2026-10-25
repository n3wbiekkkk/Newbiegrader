/* Policy pages (privacy, terms, FAQ) share the website's saved theme.
 * The script loads in <head> so the theme is set before first paint. */
(() => {
  let theme = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  try {
    const saved = localStorage.getItem('ng_theme');
    if (saved === 'light' || saved === 'dark') theme = saved;
  } catch (e) { /* optional storage */ }

  function apply() {
    document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
    const button = document.getElementById('legal-theme');
    if (!button) return;
    const action = theme === 'dark' ? 'ใช้ธีมสว่าง' : 'ใช้ธีมมืด';
    button.setAttribute('aria-label', action);
    button.title = action;
  }

  function toggle() {
    theme = theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem('ng_theme', theme); } catch (e) { /* optional storage */ }
    apply();
  }

  apply();
  document.addEventListener('DOMContentLoaded', () => {
    apply();
    const button = document.getElementById('legal-theme');
    if (button) button.addEventListener('click', toggle);

    const contents = document.querySelector('.legal-toc');
    if (contents && matchMedia('(max-width: 900px)').matches) contents.open = false;

    // The navigation wraps on mobile and at larger text sizes. Use its actual
    // height so heading anchors and the skip link stay below the sticky bar.
    const header = document.querySelector('.legal-topbar');
    function sizeHeader() {
      if (header) document.documentElement.style.setProperty(
        '--legal-header-height', `${Math.ceil(header.getBoundingClientRect().height)}px`);
    }
    sizeHeader();
    if (header && typeof ResizeObserver !== 'undefined') new ResizeObserver(sizeHeader).observe(header);

    function revealQuestion() {
      let id;
      try { id = decodeURIComponent(location.hash.slice(1)); } catch (e) { return; }
      const question = document.getElementById(id);
      if (question && question.tagName === 'DETAILS') question.open = true;
    }
    revealQuestion();
    window.addEventListener('hashchange', revealQuestion);

    // Print every answer, then restore the reader's chosen disclosure state.
    let printState = null;
    window.addEventListener('beforeprint', () => {
      if (printState) return;
      printState = Array.from(document.querySelectorAll('.legal-faq details'), item => [item, item.open]);
      printState.forEach(([item]) => { item.open = true; });
    });
    window.addEventListener('afterprint', () => {
      if (!printState) return;
      printState.forEach(([item, open]) => { item.open = open; });
      printState = null;
    });
  });
})();
