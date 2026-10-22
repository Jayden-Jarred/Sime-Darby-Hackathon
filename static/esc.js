// Escape text before it goes into HTML built from data (names, notes, messages).
// One copy, imported by house3d.js and the page scripts.
export const esc = s => String(s).replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
