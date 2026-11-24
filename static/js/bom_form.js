// New BOM / edit BOM (app/boms.py): room-wise measurements. Sizes typed in the business's unit (Settings → Units) and
// sent in feet, like every size in the app; areas shown in sq ft or sq m.
(() => {
  const U = window.KI_UNITS || { size: 'ftin', perFoot: null, sizeLabel: 'ft & in', areaLabel: 'sqft', areaFactor: 1 };
  const METRIC = U.size !== 'ftin';
  const tbody = document.getElementById('bom_areas');
  let n = 0;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = sqft => (sqft * U.areaFactor).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function split(feet) {               // feet → what's typed: {a: feet or metric value, b: inches}
    if (!feet) return { a: '', b: '' };
    if (METRIC) { const v = feet * U.perFoot; return { a: U.size === 'mm' ? Math.round(v) : Math.round(v * 10) / 10, b: '' }; }
    let ft = Math.floor(feet), inch = Math.round((feet - ft) * 12);
    if (inch === 12) { ft++; inch = 0; }
    return { a: ft, b: inch || '' };
  }
  function size(id) {
    const a = parseFloat(document.getElementById(id + 'a')?.value || 0) || 0;
    const b = parseFloat(document.getElementById(id + 'b')?.value || 0) || 0;
    const v = METRIC ? a / U.perFoot : a + b / 12;
    return v > 0 && isFinite(v) ? Math.round(v * 1e6) / 1e6 : 0;
  }
  function sizeCell(id, feet) {
    const s = split(feet);
    if (METRIC) return `<div class="input-group input-group-sm"><input type="number" class="form-control text-center" id="${id}a"
        min="0" step="any" value="${s.a}" aria-label="${esc(U.sizeLabel)}"><span class="input-group-text">${esc(U.sizeLabel)}</span></div>`;
    return `<div class="input-group input-group-sm">
        <input type="number" class="form-control text-center px-1" id="${id}a" min="0" max="999" step="1" value="${s.a}" aria-label="Feet">
        <span class="input-group-text px-1">ft</span>
        <input type="number" class="form-control text-center px-1" id="${id}b" min="0" max="11" step="1" value="${s.b}" aria-label="Inches">
        <span class="input-group-text px-1">in</span></div>`;
  }

  window.bomAddRow = (name, length, width, focus = true) => {
    const k = ++n;
    const tr = document.createElement('tr');
    tr.dataset.k = k;
    tr.innerHTML = `<td><input type="text" class="form-control form-control-sm" id="bn${k}" maxlength="60" list="bomRoomNames"
          placeholder="e.g. Living room" value="${esc(name || '')}" autocomplete="off"></td>
        <td>${sizeCell('bl' + k, length)}</td><td>${sizeCell('bw' + k, width)}</td>
        <td class="text-end fw-semibold" id="ba${k}"></td>
        <td><button type="button" class="btn btn-sm btn-outline-danger px-1 py-0" title="Remove" aria-label="Remove"><i class="bi bi-x-lg"></i></button></td>`;
    tr.querySelector('button').addEventListener('click', () => { tr.remove(); recalc(); });
    tbody.appendChild(tr);
    if (focus && name === undefined) document.getElementById('bn' + k).focus();
    recalc();
  };

  function rows() {
    return [...tbody.querySelectorAll('tr[data-k]')].map(tr => {
      const k = tr.dataset.k;
      return { name: (document.getElementById('bn' + k).value || '').trim(), length: size('bl' + k), width: size('bw' + k) };
    }).filter(r => r.name || r.length || r.width);
  }
  function recalc() {
    let total = 0;
    tbody.querySelectorAll('tr[data-k]').forEach(tr => {
      const k = tr.dataset.k, a = size('bl' + k) * size('bw' + k);
      total += a;
      document.getElementById('ba' + k).textContent = a ? fmt(a) : '';
    });
    document.getElementById('bom_total').textContent = fmt(total);
    document.getElementById('bom_total_badge').textContent = fmt(total) + ' ' + U.areaLabel;
  }
  tbody.addEventListener('input', recalc);
  // Enter in a row's last box adds the next row instead of saving
  tbody.addEventListener('keydown', e => {
    if (e.key !== 'Enter' || e.target.tagName !== 'INPUT') return;
    e.preventDefault();
    const tr = e.target.closest('tr');
    if (tr === tbody.lastElementChild) bomAddRow(); else tr.nextElementSibling.querySelector('input')?.focus();
  });
  window.bomSubmit = () => { document.getElementById('bom_areas_field').value = JSON.stringify(rows()); return true; };

  let saved = [];
  try { saved = JSON.parse(document.getElementById('bom-areas-data').textContent || '[]'); } catch (e) { saved = []; }
  saved.forEach(r => bomAddRow(r.name, r.length, r.width, false));
  if (!saved.length) for (let i = 0; i < 3; i++) bomAddRow('', 0, 0, false);
})();
