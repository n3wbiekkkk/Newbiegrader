/* Policy pages (privacy, terms, FAQ) share the website's saved theme.
 * The script loads in <head> so the theme is set before first paint. */
(() => {
  let theme = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  try { theme = localStorage.getItem('ng_theme') || theme; } catch (e) { /* optional storage */ }

  function apply() {
    document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
    const button = document.getElementById('legal-theme');
    if (!button) return;
    button.textContent = theme === 'dark' ? 'ใช้ธีมสว่าง' : 'ใช้ธีมมืด';
    button.setAttribute('aria-pressed', String(theme === 'dark'));
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
  });
})();
