/* Standalone policy pages share the website's saved theme. */
(() => {
  let theme = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  try { theme = localStorage.getItem('ng_theme') || theme; } catch (e) { /* optional storage */ }
  const button = document.getElementById('legal-theme');
  function apply() {
    document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
    if (button) button.textContent = theme === 'dark' ? 'ใช้ธีมสว่าง' : 'ใช้ธีมมืด';
  }
  apply();
  if (button) button.addEventListener('click', () => {
    theme = theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem('ng_theme', theme); } catch (e) { /* optional storage */ }
    apply();
  });
})();
