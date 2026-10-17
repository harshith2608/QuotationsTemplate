/**
 * Dynamic Project Form
 * Measurements are entered as Feet + Inches and converted to decimal feet for calculation.
 */

'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
let itemRates = {};  // { 'wood|work': rate }
let roomCounter = 0;
const rooms = {};  // { roomKey: { name, items: { itemKey: { name, lengthFt, lengthIn, widthFt, widthIn, wood_type, work_type } } } }
let masterRooms = [];
let masterItems = [];
let priceList = [];           // [{name, price, unit}] — fittings & accessories (Admin → Rates)
let modalItemType = 'measured';
let modalPriceTouched = false;

// Material catalogue — injected by templates/projects/form.html from app/catalog.py
const CATALOG = window.KI_CATALOG || { combos: [], defaultWood: '', defaultWork: '' };
// 'Material|Work Type'; materials with a single rate (e.g. Glass) have an empty work type: 'Glass|'
function splitCombo(value) {
  const i = (value || '').indexOf('|');
  return i < 0 ? [CATALOG.defaultWood, CATALOG.defaultWork] : [value.slice(0, i), value.slice(i + 1)];
}
function comboLabel(wood, work) { return work ? `${wood} – ${work}` : (wood || ''); }
const DEFAULT_COMBO = CATALOG.defaultWood + '|' + CATALOG.defaultWork;

// ─── Plywood pricing ──────────────────────────────────────────────────────────
// Rates are for the business's default plywood. A plywood material on another plywood has its own rate under the key
// 'Material|Work|Plywood' (sent by the server in itemRates). The quotation picks a plywood; an item can use its own.
const PLY = window.KI_PLYWOOD || { enabled: false, default: null, materials: [], options: [] };
function quotationPly() {
  const r = document.querySelector('input[name="plywood"]:checked');
  return r ? r.value : PLY.default;
}
function usesPly(wood) { return PLY.enabled && PLY.materials.includes(wood); }
function priceKey(wood, work, itemPly) {
  const base = `${wood}|${work || ''}`;
  const eff = itemPly || quotationPly();
  if (!usesPly(wood) || !eff || eff === PLY.default || !PLY.options.some(o => o.name === eff)) return base;
  return `${base}|${eff}`;
}
function parseKey(key) {                      // 'Material|Work|Plywood' → [wood, work, plywood|null]
  const p = (key || '').split('|');
  return [p[0], p[1] || '', p[2] || null];
}
function keyLabel(key) {
  const [wood, work, ply] = parseKey(key);
  let label = comboLabel(wood, work);
  if (ply) label += ' · ' + ply;
  else if (usesPly(wood) && PLY.default) label += ' · ' + PLY.default;    // same naming as the PDFs
  return label;
}
function plyOptions(selected, wood) {
  // '' = follow the quotation's plywood
  const q = quotationPly();
  let html = `<option value="">Quotation's plywood${q ? ' (' + escHtml(q) + ')' : ''}</option>`;
  PLY.options.forEach(o => {
    if (!o.active && o.name !== selected) return;
    const diff = o.name === PLY.default ? '' : (o.delta ? ` (${o.delta > 0 ? '+' : ''}${o.delta} ₹/sqft)` : '');
    html += `<option value="${escHtml(o.name)}" ${o.name === selected ? 'selected' : ''}>${escHtml(o.name)}${diff}</option>`;
  });
  return html;
}
function onQuotationPlywood() {
  // Refresh the "Quotation's plywood (…)" wording in every item picker, then re-price
  document.querySelectorAll('select[id^="item_ply_"]').forEach(sel => {
    const v = sel.value; sel.innerHTML = plyOptions(v); sel.value = v;
  });
  recalcAll();
}
function syncPlyVisibility(ik, wood) {
  const wrap = document.getElementById('item_ply_wrap_' + ik);
  if (wrap) wrap.style.display = usesPly(wood) ? '' : 'none';
}
function syncModalPly() {
  const wrap = document.getElementById('modal_ply_wrap');
  if (!wrap) return;
  const [wood] = splitCombo(document.getElementById('modal_item_combo')?.value || DEFAULT_COMBO);
  wrap.style.display = usesPly(wood) && modalItemType !== 'fixed' ? '' : 'none';
}

// ─── Draft Auto-Save ──────────────────────────────────────────────────────────
// Only active on the New Quotation form (IS_DRAFT_FORM = true, set by template).
// Saves customer name/mobile/email to the server 3 s after the last keystroke.
// The returned draft_id is stored in a hidden field so the final submit can
// promote the draft to complete instead of creating a duplicate record.
let _draftSaveTimer = null;

function scheduleDraftSave() {
  if (typeof IS_DRAFT_FORM === 'undefined' || !IS_DRAFT_FORM) return;
  clearTimeout(_draftSaveTimer);
  _draftSaveTimer = setTimeout(_doSaveDraft, 3000);
}

async function _doSaveDraft() {
  const customerName = (document.getElementById('customer_name') || {}).value || '';
  if (!customerName.trim()) return;   // don't create a draft with no name

  const mobile   = (document.getElementById('mobile') || {}).value || '';
  const email    = (document.getElementById('email')  || {}).value || '';
  const draftField = document.getElementById('draft_id_field');
  const draftId    = draftField ? draftField.value : '';
  const csrf = (document.querySelector('input[name="csrf_token"]') || {}).value || '';

  // Build current rooms payload (partial data is fine — skip incomplete items)
  const roomsPayload = [];
  Object.entries(rooms).forEach(([rk, room]) => {
    const nameInput = document.getElementById('room_name_' + rk);
    const roomName  = nameInput ? nameInput.value.trim() : (room.name || '');
    if (!roomName) return;
    const itemsPayload = [];
    Object.values(room.items).forEach(item => {
      const p = _itemPayload(item);
      if (p) itemsPayload.push(p);
    });
    roomsPayload.push({ name: roomName, items: itemsPayload });
  });

  try {
    const resp = await fetch('/api/draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify({
        draft_id: draftId || null,
        customer_name: customerName, mobile, email,
        ...(PLY.enabled ? { plywood: quotationPly() } : {}),
        rooms_data: roomsPayload
      })
    });
    if (resp.ok) {
      const data = await resp.json();
      if (draftField && data.draft_id) draftField.value = data.draft_id;
      _showDraftIndicator();
    }
  } catch (_) { /* silent — auto-save is best-effort */ }
}

function _showDraftIndicator() {
  let el = document.getElementById('draft-saved-indicator');
  if (!el) {
    el = document.createElement('span');
    el.id = 'draft-saved-indicator';
    el.className = 'text-muted small ms-2';
    const header = document.querySelector('.ki-page-title');
    if (header) header.appendChild(el);
  }
  el.innerHTML = '<i class="bi bi-clock me-1"></i>Draft saved';
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => { el.innerHTML = ''; }, 4000);
}


// ─── Conversion helpers ───────────────────────────────────────────────────────
function ftInToDecimal(ft, inch) {
  return parseFloat(ft || 0) + parseFloat(inch || 0) / 12;
}

function decimalToFtIn(decimal) {
  if (!decimal || isNaN(decimal)) return { ft: 0, inch: 0 };
  let ft = Math.floor(decimal);
  let inch = Math.round((decimal - ft) * 12);
  if (inch === 12) { ft++; inch = 0; }
  return { ft, inch };
}

// ─── Custom Autocomplete ──────────────────────────────────────────────────────
// Strategy: dropdown appended to <body> with position:absolute so no ancestor
// overflow:hidden/auto can clip it. Positioned ONCE when opened; closed on
// scroll/touchmove (no continuous repositioning → no jitter on mobile).
function initAutocomplete(input, suggestions) {
  // suggestions: an array, or a function returning the current array
  const getList = typeof suggestions === 'function' ? suggestions : () => suggestions;
  if (!input || !suggestions || (typeof suggestions !== 'function' && !suggestions.length)) return;

  const ul = document.createElement('ul');
  ul.className = 'ki-ac-dropdown';
  ul.style.cssText = 'position:absolute;z-index:9999;display:none;';
  document.body.appendChild(ul);
  input._kiAcUl = ul;

  const close = () => { ul.style.display = 'none'; };

  function position() {
    const r = input.getBoundingClientRect();
    ul.style.top   = (r.bottom + window.scrollY) + 'px';
    ul.style.left  = (r.left   + window.scrollX) + 'px';
    ul.style.width = r.width + 'px';
  }

  function render() {
    const q = input.value.trim().toLowerCase();
    const all = getList() || [];
    const list = q ? all.filter(s => s.toLowerCase().includes(q)) : all;
    if (!list.length) { close(); return; }
    ul.innerHTML = list.map(s => `<li>${escHtml(s)}</li>`).join('');
    position();
    ul.style.display = 'block';
  }

  // Prevent iOS long-press context menu (Paste / Autofill / Look Up)
  ul.addEventListener('contextmenu', e => e.preventDefault());

  // Track touch movement so we can tell a tap apart from a scroll.
  // We call preventDefault() on touchstart (non-passive) to kill the iOS
  // long-press callout, then manually scroll the list in touchmove.
  let _touchStartY = 0;
  let _touchMoved  = false;
  let _ulScrollTop = 0;
  ul.addEventListener('touchstart', e => {
    _touchStartY = e.touches[0].clientY;
    _touchMoved  = false;
    _ulScrollTop = ul.scrollTop;
    e.preventDefault(); // blocks iOS long-press callout (Paste/Autofill)
  }, { passive: false });
  ul.addEventListener('touchmove', e => {
    const dy = _touchStartY - e.touches[0].clientY;
    if (Math.abs(dy) > 8) {
      _touchMoved  = true;
      ul.scrollTop = _ulScrollTop + dy; // manual scroll since native is blocked
    }
  }, { passive: true });

  // Event delegation on the ul — works for both mouse and touch
  ul.addEventListener('mousedown', e => {
    const li = e.target.closest('li');
    if (!li) return;
    e.preventDefault();
    input.value = li.textContent;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    close();
  });
  ul.addEventListener('touchend', e => {
    if (_touchMoved) return;          // finger scrolled — don't select
    const li = e.target.closest('li');
    if (!li) return;
    e.preventDefault();
    input.value = li.textContent;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    close();
    // Don't call input.focus() here — it would reopen the dropdown via the focus listener
  });

  input.addEventListener('focus',  render);
  input.addEventListener('click',  render);
  input.addEventListener('input',  render);
  input.addEventListener('blur',   () => setTimeout(close, 200));

  // Close when page scrolls, but NOT when the user is scrolling inside the dropdown
  window.addEventListener('scroll', close, { passive: true });
  document.addEventListener('touchmove', e => {
    if (!ul.contains(e.target)) close();
  }, { passive: true });
}

// Tear down autocomplete when a room/item row is removed (prevent memory leaks)
function _destroyAc(containerEl) {
  if (!containerEl) return;
  containerEl.querySelectorAll('input').forEach(inp => {
    if (inp._kiAcUl) { inp._kiAcUl.remove(); inp._kiAcUl = null; }
  });
}

function _readDatalist(id) {
  const dl = document.getElementById(id);
  if (!dl) return [];
  return Array.from(dl.options).map(o => o.value).filter(Boolean);
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  try { itemRates = JSON.parse(document.getElementById('item-rates-data').textContent || '{}'); } catch (e) { itemRates = {}; }

  // Populate suggestion lists from datalist elements in HTML
  masterRooms = _readDatalist('master-rooms-list');
  masterItems = _readDatalist('master-items-list');

  try { priceList = JSON.parse(document.getElementById('price-list-data').textContent || '[]'); } catch (e) { priceList = []; }

  document.getElementById('modal_item_combo')?.addEventListener('change', syncModalPly);

  // Modal item name: suggests room items for measured, the price list for fixed-price items
  const modalNameInput = document.getElementById('modal_item_name');
  if (modalNameInput) {
    initAutocomplete(modalNameInput, () => modalItemType === 'fixed' ? priceList.map(p => p.name) : masterItems);
    modalNameInput.addEventListener('input', () => { if (modalItemType === 'fixed') _applyPriceListPrice(); });
  }

  // Restore the saved discount (edit mode) BEFORE the first recalculation: recalcAll()
  // copies the discount controls into the hidden fields, so restoring afterwards would
  // read back "none" and saving the quotation would silently drop its discount.
  const savedType  = (document.getElementById('discount_type_field')  || {}).value || 'none';
  const savedValue = (document.getElementById('discount_value_field') || {}).value || '0';
  const dtypeEl = document.getElementById('discount_type_select');
  const dvalEl  = document.getElementById('discount_value_input');
  if (dtypeEl && savedType !== 'none') {
    dtypeEl.value = savedType;
    if (dvalEl) { dvalEl.value = savedValue; dvalEl.style.display = 'block'; }
  }

  let existingRooms = [];
  try { existingRooms = JSON.parse(document.getElementById('existing-rooms-data').textContent || '[]'); }
  catch (e) { existingRooms = []; }

  if (existingRooms && existingRooms.length > 0) {
    existingRooms.forEach(rd => {
      const rk = addRoom(rd.name);
      (rd.items || []).forEach(id => {
        if (id.type === 'fixed') { _insertFixedRow(rk, id.name, id.quantity, id.unit_price); return; }
        const lFtIn = decimalToFtIn(id.length);
        const wFtIn = decimalToFtIn(id.width);
        addItem(rk, id.name, lFtIn.ft, lFtIn.inch, wFtIn.ft, wFtIn.inch, id.wood_type, id.work_type, id.plywood || '');
      });
    });
  }

  updateNoRoomsHint();
  recalcAll();

  // Attach auto-save listeners to customer fields (new form only)
  ['customer_name', 'mobile', 'email'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', scheduleDraftSave);
  });


  // Allow pressing Enter in modal fields to save
  const itemModalEl = document.getElementById('itemModal');
  if (itemModalEl) {
    itemModalEl.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') {
        e.preventDefault();
        saveItemFromModal();
      }
    });
  }
});

// ─── Room Management ──────────────────────────────────────────────────────────
function addRoom(presetName) {
  roomCounter++;
  const rk = 'room_' + roomCounter;
  rooms[rk] = { name: presetName || '', items: {} };

  const container = document.getElementById('rooms-container');
  const div = document.createElement('div');
  div.className = 'card shadow-sm mb-3 room-card';
  div.id = 'room_card_' + rk;
  div.innerHTML = `
    <div class="card-header d-flex align-items-center gap-2 py-2">
      <i class="bi bi-door-open text-primary"></i>
      <div class="ki-ac-wrap" style="max-width:280px">
        <input type="text"
               class="form-control form-control-sm fw-semibold"
               id="room_name_${rk}"
               placeholder="Room name (e.g. Living Room)"
               value="${escHtml(presetName || '')}"
               oninput="onRoomNameChange('${rk}', this.value)"
               autocomplete="off">
      </div>
      <span class="badge bg-primary ms-auto me-1" id="room_total_badge_${rk}">0.00 sqft</span>
      <button type="button" class="btn btn-sm btn-outline-danger" onclick="removeRoom('${rk}')" title="Remove Room">
        <i class="bi bi-trash"></i>
      </button>
    </div>
    <div class="card-body p-2 p-md-3">
      <div class="item-table-wrap">
        <table class="table table-sm table-bordered item-table mb-2">
          <thead>
            <tr>
              <th style="min-width:150px">Item Name</th>
              <th style="min-width:155px">Length</th>
              <th style="min-width:155px">Width</th>
              <th style="min-width:180px">Material &amp; Work</th>
              <th style="min-width:80px">Area (sqft)</th>
              <th style="width:36px"></th>
            </tr>
          </thead>
          <tbody id="items_tbody_${rk}"></tbody>
        </table>
      </div>
      <button type="button" class="btn btn-sm btn-outline-primary" onclick="addItem('${rk}')">
        <i class="bi bi-plus me-1"></i>Add Item
      </button>
    </div>
  `;
  container.appendChild(div);
  // Wire up autocomplete for room name input
  const roomNameInput = document.getElementById('room_name_' + rk);
  if (roomNameInput && masterRooms.length) initAutocomplete(roomNameInput, masterRooms);
  updateNoRoomsHint();
  return rk;
}

function removeRoom(rk) {
  const card = document.getElementById('room_card_' + rk);
  _destroyAc(card);
  if (card) card.remove();
  delete rooms[rk];
  updateNoRoomsHint();
  recalcAll();
}

function onRoomNameChange(rk, val) {
  if (rooms[rk]) rooms[rk].name = val.trim();
}

// ─── Item Management ──────────────────────────────────────────────────────────
let itemCounter = 0;
let _modalRoomKey = null;

// Public: called by "Add Item" button — opens modal for user entry.
// Also called internally with preset values when loading existing data.
function addItem(rk, presetName, presetLFt, presetLIn, presetWFt, presetWIn, presetWood, presetWork, presetPly) {
  if (presetName === undefined && presetLFt === undefined) {
    // User clicked "Add Item" — open modal
    openItemModal(rk);
    return;
  }
  _insertItemRow(rk, presetName, presetLFt, presetLIn, presetWFt, presetWIn, presetWood, presetWork, presetPly);
}

function openItemModal(rk) {
  _modalRoomKey = rk;
  const nameEl = document.getElementById('modal_item_name');
  if (nameEl) { nameEl.value = ''; nameEl.classList.remove('is-invalid'); }
  ['modal_item_lft','modal_item_lin','modal_item_wft','modal_item_win'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  const comboEl = document.getElementById('modal_item_combo');
  if (comboEl) comboEl.value = DEFAULT_COMBO;
  const plyEl = document.getElementById('modal_item_ply');
  if (plyEl) { plyEl.innerHTML = plyOptions(''); plyEl.value = ''; }
  const areaEl = document.getElementById('modal_item_area');
  if (areaEl) areaEl.textContent = '0.00';
  const qtyEl = document.getElementById('modal_item_qty');     if (qtyEl) qtyEl.value = 1;
  const priceEl = document.getElementById('modal_item_price'); if (priceEl) priceEl.value = '';
  modalPriceTouched = false;
  const measuredRadio = document.getElementById('modal_type_measured');
  if (measuredRadio) measuredRadio.checked = true;
  setModalItemType('measured');
  syncModalPly();
  const modal = new bootstrap.Modal(document.getElementById('itemModal'));
  modal.show();
  setTimeout(() => { if (nameEl) nameEl.focus(); }, 350);
}

function modalCalcArea() {
  const lFt  = parseFloat(document.getElementById('modal_item_lft')?.value) || 0;
  const lIn  = parseFloat(document.getElementById('modal_item_lin')?.value) || 0;
  const wFt  = parseFloat(document.getElementById('modal_item_wft')?.value) || 0;
  const wIn  = parseFloat(document.getElementById('modal_item_win')?.value) || 0;
  // clamp inches
  if (lIn > 11) document.getElementById('modal_item_lin').value = 11;
  if (wIn > 11) document.getElementById('modal_item_win').value = 11;
  const area = ftInToDecimal(lFt, lIn) * ftInToDecimal(wFt, wIn);
  const el = document.getElementById('modal_item_area');
  if (el) el.textContent = area.toFixed(2);
}

// ─── Fixed-price items (fittings & accessories) ──────────────────────────────
function setModalItemType(type) {
  modalItemType = type;
  document.getElementById('modal_fixed_fields')?.classList.toggle('d-none', type !== 'fixed');
  document.getElementById('modal_measured_fields')?.classList.toggle('d-none', type === 'fixed');
  const nameEl = document.getElementById('modal_item_name');
  if (nameEl) nameEl.placeholder = type === 'fixed' ? 'e.g. Magic Corner' : 'e.g. Wardrobe';
  if (type === 'fixed') { _applyPriceListPrice(); modalCalcFixed(); }
  syncModalPly();
}

function _findPrice(name) {
  const n = (name || '').trim().toLowerCase();
  return priceList.find(p => p.name.toLowerCase() === n);
}

// Fill the unit price from the price list when the name matches (unless the user typed a price)
function _applyPriceListPrice() {
  const match = _findPrice(document.getElementById('modal_item_name')?.value);
  const priceEl = document.getElementById('modal_item_price');
  const hint = document.getElementById('modal_price_hint');
  if (match && priceEl && !modalPriceTouched) priceEl.value = match.price;
  if (hint) hint.textContent = match
    ? `From your price list: ₹${match.price.toLocaleString('en-IN')}${match.unit ? ' per ' + match.unit : ''}. You can change it for this quotation.`
    : 'Pick an item from your price list to fill in the price, or type your own.';
  modalCalcFixed();
}

function modalCalcFixed() {
  const qty   = parseFloat(document.getElementById('modal_item_qty')?.value) || 0;
  const price = parseFloat(document.getElementById('modal_item_price')?.value) || 0;
  const el = document.getElementById('modal_item_amount');
  if (el) el.textContent = '₹' + (qty * price).toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

function _insertFixedRow(rk, name, quantity, unitPrice) {
  itemCounter++;
  const ik = 'item_' + itemCounter;
  if (!rooms[rk]) return;
  const qty = quantity !== undefined && quantity !== null ? quantity : 1;
  const price = unitPrice !== undefined && unitPrice !== null ? unitPrice : '';
  rooms[rk].items[ik] = { type: 'fixed', name: name || '', quantity: parseFloat(qty) || 0, unit_price: parseFloat(price) || 0 };

  const tbody = document.getElementById('items_tbody_' + rk);
  if (!tbody) return;
  const tr = document.createElement('tr');
  tr.className = 'item-row item-row-fixed';
  tr.id = 'item_row_' + ik;
  tr.innerHTML = `
    <td>
      <div class="ki-ac-wrap">
        <input type="text" class="form-control form-control-sm" id="item_name_${ik}"
               placeholder="e.g. Magic Corner" value="${escHtml(name || '')}"
               oninput="onFixedField('${rk}','${ik}')" autocomplete="off">
      </div>
    </td>
    <td colspan="2">
      <div class="input-group input-group-sm">
        <span class="input-group-text px-2 small text-muted">Qty</span>
        <input type="number" class="form-control text-center px-1" id="item_qty_${ik}" min="0" step="any"
               value="${qty}" oninput="onFixedField('${rk}','${ik}')" style="max-width:64px" title="Quantity">
        <span class="input-group-text px-2 small text-muted">× ₹</span>
        <input type="number" class="form-control text-end px-1" id="item_price_${ik}" min="0" step="any"
               value="${price}" oninput="onFixedField('${rk}','${ik}')" title="Price per unit">
      </div>
    </td>
    <td class="text-center"><span class="badge ki-badge-fitting">Fitting</span></td>
    <td class="text-center">
      <span class="area-display fw-bold text-primary" id="item_amount_${ik}"></span>
    </td>
    <td class="text-center">
      <button type="button" class="btn btn-outline-danger btn-remove-item"
              onclick="removeItem('${rk}','${ik}')" title="Remove">
        <i class="bi bi-x-lg"></i>
      </button>
    </td>`;
  tbody.appendChild(tr);
  const nameInput = document.getElementById('item_name_' + ik);
  if (nameInput && priceList.length) initAutocomplete(nameInput, () => priceList.map(p => p.name));
  onFixedField(rk, ik);
}

function onFixedField(rk, ik) {
  if (!rooms[rk] || !rooms[rk].items[ik]) return;
  const nameEl  = document.getElementById('item_name_'  + ik);
  const qtyEl   = document.getElementById('item_qty_'   + ik);
  const priceEl = document.getElementById('item_price_' + ik);
  // Picking a price-list name in an empty-price row fills the price
  const match = _findPrice(nameEl?.value);
  if (match && priceEl && priceEl.value === '') priceEl.value = match.price;
  const quantity   = parseFloat(qtyEl?.value) || 0;
  const unit_price = parseFloat(priceEl?.value) || 0;
  rooms[rk].items[ik] = { type: 'fixed', name: nameEl?.value.trim() || '', quantity, unit_price };
  const amtEl = document.getElementById('item_amount_' + ik);
  if (amtEl) amtEl.textContent = '₹' + (quantity * unit_price).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  recalcAll();
}

// Serialise one item for the server; returns null if incomplete
function _itemPayload(item) {
  if (item.type === 'fixed') {
    if (!item.name || !(item.quantity > 0) || !(item.unit_price >= 0)) return null;
    return { type: 'fixed', name: item.name, quantity: item.quantity, unit_price: item.unit_price };
  }
  const lDec = ftInToDecimal(item.lengthFt || 0, item.lengthIn || 0);
  const wDec = ftInToDecimal(item.widthFt  || 0, item.widthIn  || 0);
  if (!item.name || lDec <= 0 || wDec <= 0) return null;
  return {
    name: item.name, length: lDec, width: wDec,
    wood_type: item.wood_type, work_type: item.work_type,
    plywood: usesPly(item.wood_type) ? (item.plywood || '') : '',
    area: item.area || parseFloat((lDec * wDec).toFixed(4))
  };
}

function saveItemFromModal() {
  const nameEl = document.getElementById('modal_item_name');
  const name   = nameEl?.value.trim() || '';
  if (!name) { if (nameEl) nameEl.classList.add('is-invalid'); return; }
  if (nameEl) nameEl.classList.remove('is-invalid');

  if (modalItemType === 'fixed') {
    const qty   = parseFloat(document.getElementById('modal_item_qty')?.value) || 0;
    const price = parseFloat(document.getElementById('modal_item_price')?.value);
    const qtyEl = document.getElementById('modal_item_qty');
    const priceEl = document.getElementById('modal_item_price');
    qtyEl?.classList.toggle('is-invalid', !(qty > 0));
    priceEl?.classList.toggle('is-invalid', isNaN(price) || price < 0);
    if (!(qty > 0) || isNaN(price) || price < 0) return;
    _insertFixedRow(_modalRoomKey, name, qty, price);
    const inst = bootstrap.Modal.getInstance(document.getElementById('itemModal'));
    if (inst) inst.hide();
    return;
  }

  const lFt  = parseFloat(document.getElementById('modal_item_lft')?.value) || 0;
  const lIn  = parseFloat(document.getElementById('modal_item_lin')?.value) || 0;
  const wFt  = parseFloat(document.getElementById('modal_item_wft')?.value) || 0;
  const wIn  = parseFloat(document.getElementById('modal_item_win')?.value) || 0;
  const [wood, work] = splitCombo(document.getElementById('modal_item_combo')?.value || DEFAULT_COMBO);
  const ply = document.getElementById('modal_item_ply')?.value || '';

  _insertItemRow(_modalRoomKey, name, lFt, lIn, wFt, wIn, wood, work, ply);

  const modalEl = document.getElementById('itemModal');
  const instance = bootstrap.Modal.getInstance(modalEl);
  if (instance) instance.hide();
}

// Internal: inserts an item row directly into the table (used when loading
// existing data and after modal save).
function _insertItemRow(rk, presetName, presetLFt, presetLIn, presetWFt, presetWIn, presetWood, presetWork, presetPly) {
  itemCounter++;
  const ik = 'item_' + itemCounter;
  if (!rooms[rk]) return;

  const lFt  = presetLFt  !== undefined ? presetLFt  : '';
  const lIn  = presetLIn  !== undefined ? presetLIn  : '';
  const wFt  = presetWFt  !== undefined ? presetWFt  : '';
  const wIn  = presetWIn  !== undefined ? presetWIn  : '';
  const wood = presetWood || CATALOG.defaultWood;
  const work = presetWood ? (presetWork || '') : CATALOG.defaultWork;   // '' is a real value (single-rate material)
  const name = presetName || '';

  const lDec = ftInToDecimal(lFt, lIn);
  const wDec = ftInToDecimal(wFt, wIn);
  const area  = parseFloat((lDec * wDec).toFixed(4));

  const ply = presetPly || '';
  rooms[rk].items[ik] = {
    name, lengthFt: lFt, lengthIn: lIn, widthFt: wFt, widthIn: wIn,
    wood_type: wood, work_type: work, plywood: ply, area
  };

  const tbody = document.getElementById('items_tbody_' + rk);
  if (!tbody) return;

  const tr = document.createElement('tr');
  tr.className = 'item-row';
  tr.id = 'item_row_' + ik;
  tr.innerHTML = `
    <td>
      <div class="ki-ac-wrap">
        <input type="text" class="form-control form-control-sm"
               id="item_name_${ik}"
               placeholder="e.g. Wardrobe"
               value="${escHtml(name)}"
               oninput="onItemField('${rk}','${ik}')"
               autocomplete="off">
      </div>
    </td>
    <td>
      <div class="input-group input-group-sm">
        <input type="number" class="form-control text-center px-1"
               id="item_lft_${ik}" placeholder="0" min="0" max="999" step="1"
               value="${lFt}" oninput="onItemField('${rk}','${ik}')"
               style="max-width:52px" title="Feet">
        <span class="input-group-text px-1 small text-muted">ft</span>
        <input type="number" class="form-control text-center px-1"
               id="item_lin_${ik}" placeholder="0" min="0" max="11" step="1"
               value="${lIn}" oninput="onItemField('${rk}','${ik}')"
               style="max-width:52px" title="Inches (0–11)">
        <span class="input-group-text px-1 small text-muted">in</span>
      </div>
    </td>
    <td>
      <div class="input-group input-group-sm">
        <input type="number" class="form-control text-center px-1"
               id="item_wft_${ik}" placeholder="0" min="0" max="999" step="1"
               value="${wFt}" oninput="onItemField('${rk}','${ik}')"
               style="max-width:52px" title="Feet">
        <span class="input-group-text px-1 small text-muted">ft</span>
        <input type="number" class="form-control text-center px-1"
               id="item_win_${ik}" placeholder="0" min="0" max="11" step="1"
               value="${wIn}" oninput="onItemField('${rk}','${ik}')"
               style="max-width:52px" title="Inches (0–11)">
        <span class="input-group-text px-1 small text-muted">in</span>
      </div>
    </td>
    <td>
      <select class="form-select form-select-sm"
              id="item_combo_${ik}"
              onchange="onItemField('${rk}','${ik}')">
        ${buildComboOptions(wood, work)}
      </select>
      ${PLY.enabled ? `<div id="item_ply_wrap_${ik}" class="mt-1" style="${usesPly(wood) ? '' : 'display:none'}">
        <select class="form-select form-select-sm" id="item_ply_${ik}" title="Plywood for this item"
                onchange="onItemField('${rk}','${ik}')">${plyOptions(ply)}</select></div>` : ''}
    </td>
    <td class="text-center">
      <span class="area-display fw-bold text-primary" id="item_area_${ik}">
        ${area > 0 ? area.toFixed(2) : '0.00'}
      </span>
    </td>
    <td class="text-center">
      <button type="button" class="btn btn-outline-danger btn-remove-item"
              onclick="removeItem('${rk}','${ik}')" title="Remove">
        <i class="bi bi-x-lg"></i>
      </button>
    </td>
  `;
  tbody.appendChild(tr);
  // Wire up autocomplete for item name input
  const itemNameInput = document.getElementById('item_name_' + ik);
  if (itemNameInput && masterItems.length) initAutocomplete(itemNameInput, masterItems);
  if (area > 0) recalcAll();
}

function removeItem(rk, ik) {
  const row = document.getElementById('item_row_' + ik);
  _destroyAc(row);
  if (row) row.remove();
  if (rooms[rk] && rooms[rk].items) delete rooms[rk].items[ik];
  recalcAll();
}

function onItemField(rk, ik) {
  if (!rooms[rk] || !rooms[rk].items[ik]) return;

  const nameEl  = document.getElementById('item_name_'  + ik);
  const lFtEl   = document.getElementById('item_lft_'   + ik);
  const lInEl   = document.getElementById('item_lin_'   + ik);
  const wFtEl   = document.getElementById('item_wft_'   + ik);
  const wInEl   = document.getElementById('item_win_'   + ik);
  const comboEl = document.getElementById('item_combo_' + ik);
  const areaEl  = document.getElementById('item_area_'  + ik);

  // Clamp inches 0–11
  if (lInEl && parseInt(lInEl.value) > 11) lInEl.value = 11;
  if (wInEl && parseInt(wInEl.value) > 11) wInEl.value = 11;

  const lFt  = parseFloat(lFtEl?.value) || 0;
  const lIn  = parseFloat(lInEl?.value) || 0;
  const wFt  = parseFloat(wFtEl?.value) || 0;
  const wIn  = parseFloat(wInEl?.value) || 0;

  const lDec = ftInToDecimal(lFt, lIn);
  const wDec = ftInToDecimal(wFt, wIn);
  const area  = parseFloat((lDec * wDec).toFixed(4));

  const comboParts = splitCombo(comboEl?.value || DEFAULT_COMBO);
  const plyEl = document.getElementById('item_ply_' + ik);
  rooms[rk].items[ik] = {
    name:      nameEl?.value.trim() || '',
    lengthFt:  lFt, lengthIn: lIn,
    widthFt:   wFt, widthIn:  wIn,
    wood_type: comboParts[0],
    work_type: comboParts[1],
    plywood:   plyEl ? plyEl.value : '',
    area
  };
  syncPlyVisibility(ik, comboParts[0]);

  if (areaEl) areaEl.textContent = area.toFixed(2);
  recalcAll();
}

// ─── Calculations ─────────────────────────────────────────────────────────────
function recalcAll() {
  const comboAreas = {};  // { 'wood|work': area }
  let totalArea = 0;

  let fixedTotal = 0;
  Object.entries(rooms).forEach(([rk, room]) => {
    let roomArea = 0;
    Object.values(room.items).forEach(item => {
      if (item.type === 'fixed') { fixedTotal += (item.quantity || 0) * (item.unit_price || 0); return; }
      const a = item.area || 0;
      roomArea += a;
      totalArea += a;
      const key = priceKey(item.wood_type, item.work_type, item.plywood);
      comboAreas[key] = (comboAreas[key] || 0) + a;
    });
    const badge = document.getElementById('room_total_badge_' + rk);
    if (badge) badge.textContent = roomArea.toFixed(2) + ' sqft';
  });

  let grandTotal = fixedTotal;
  Object.entries(comboAreas).forEach(([key, area]) => { grandTotal += area * (itemRates[key] || 0); });

  renderSummary(comboAreas, grandTotal, fixedTotal);

  const fmt = '₹' + grandTotal.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const gtEl = document.getElementById('grand-total-display');
  if (gtEl) gtEl.textContent = fmt;

  _updateFinalTotal(grandTotal);

  // Update boards estimate (8×4 ft = 32 sqft per board)
  const boardsBox  = document.getElementById('boards-estimate');
  const boardsArea = document.getElementById('boards-total-area');
  const boardsCnt  = document.getElementById('boards-count');
  if (boardsBox) {
    if (totalArea > 0) {
      boardsBox.style.display = '';
      if (boardsArea) boardsArea.textContent = totalArea.toFixed(2) + ' sqft';
      if (boardsCnt)  boardsCnt.textContent  = '~' + Math.ceil(totalArea / 32);
    } else {
      boardsBox.style.display = 'none';
    }
  }

  // Auto-save draft whenever the cost summary recalculates (room/item change)
  scheduleDraftSave();
}

function _updateFinalTotal(grandTotal) {
  const typeEl  = document.getElementById('discount_type_select');
  const valEl   = document.getElementById('discount_value_input');
  const rowEl   = document.getElementById('discount_row');
  const discEl  = document.getElementById('discount-amount-display');
  const finalEl = document.getElementById('final-total-display');
  const mobEl   = document.getElementById('final-total-mobile');
  const typeField = document.getElementById('discount_type_field');
  const valField  = document.getElementById('discount_value_field');

  const dtype = typeEl ? typeEl.value : 'none';
  const dval  = parseFloat(valEl ? valEl.value : 0) || 0;

  let discountAmount = 0;
  if (dtype === 'percentage') {
    discountAmount = grandTotal * dval / 100;
  } else if (dtype === 'fixed') {
    discountAmount = Math.min(dval, grandTotal);
  }
  discountAmount = Math.max(0, discountAmount);
  const finalTotal = Math.max(0, grandTotal - discountAmount);

  // Show/hide discount row
  if (rowEl) rowEl.style.display = (dtype !== 'none' && dval > 0) ? 'flex' : 'none';
  if (discEl) discEl.textContent = '- ₹' + discountAmount.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const finalFmt = '₹' + finalTotal.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (finalEl) finalEl.textContent = finalFmt;
  if (mobEl)   mobEl.textContent   = finalFmt;

  // Sync hidden form fields
  if (typeField) typeField.value = dtype;
  if (valField)  valField.value  = dval;
}

function onDiscountChange() {
  const typeEl = document.getElementById('discount_type_select');
  const valEl  = document.getElementById('discount_value_input');
  const dtype  = typeEl ? typeEl.value : 'none';

  // Show input only when a discount type is selected
  if (valEl) valEl.style.display = dtype !== 'none' ? 'block' : 'none';

  // Recalc with current grand total
  const gtEl = document.getElementById('grand-total-display');
  let grandTotal = 0;
  if (gtEl) {
    grandTotal = parseFloat(gtEl.textContent.replace(/[₹,]/g, '')) || 0;
  }
  _updateFinalTotal(grandTotal);
}

const COMBO_COLORS = {
  'Acrylic|Box Work':    { bg:'#dbeafe', color:'#1e40af' },
  'Acrylic|Frame Work':  { bg:'#bfdbfe', color:'#1e3a8a' },
  'Laminates|Box Work':  { bg:'#dcfce7', color:'#166534' },
  'Laminates|Frame Work':{ bg:'#bbf7d0', color:'#14532d' },
  'Veneer|Box Work':     { bg:'#ffedd5', color:'#9a3412' },
  'Veneer|Frame Work':   { bg:'#fed7aa', color:'#7c2d12' },
};

function renderSummary(comboAreas, grandTotal, fixedTotal) {
  const panel = document.getElementById('summary-content');
  if (!panel) return;
  const hasData = Object.values(comboAreas).some(a => a > 0) || fixedTotal > 0;
  if (!hasData) {
    panel.innerHTML = '<p class="text-muted text-center small py-2">Add rooms and items to see cost breakdown.</p>';
    return;
  }
  let html = '<div class="small fw-semibold text-muted mb-1">Cost Breakdown</div>';
  Object.entries(comboAreas).forEach(([key, area]) => {
    if (area <= 0) return;
    const rate = itemRates[key] || 0;
    const parts = parseKey(key);
    const label = keyLabel(key);
    const base = `${parts[0]}|${parts[1]}`;
    const c = COMBO_COLORS[base] || colorFor(base);
    html += `
      <div class="summary-wood-row">
        <span class="summary-wood-label">
          <span class="badge me-1" style="background:${c.bg};color:${c.color}">${escHtml(label)}</span>
        </span>
        <span class="text-muted small">${area.toFixed(2)} sqft</span>
        <span class="summary-wood-value">₹${(area*rate).toLocaleString('en-IN',{minimumFractionDigits:0,maximumFractionDigits:0})}</span>
      </div>`;
  });
  if (fixedTotal > 0) {
    html += `
      <div class="summary-wood-row">
        <span class="summary-wood-label"><span class="badge me-1 ki-badge-fitting">${escHtml(CATALOG.fixedLabel || 'Fittings & Accessories')}</span></span>
        <span class="text-muted small"></span>
        <span class="summary-wood-value">₹${fixedTotal.toLocaleString('en-IN',{minimumFractionDigits:0,maximumFractionDigits:0})}</span>
      </div>`;
  }
  panel.innerHTML = html;
}

// ─── Form Submission ───────────────────────────────────────────────────────────
// Validates and builds rooms payload. Returns true if valid, false otherwise.
function _validateForm() {
  const nameEl   = document.getElementById('customer_name');
  const mobileEl = document.getElementById('mobile');
  let valid = true;

  [nameEl, mobileEl].forEach(el => {
    if (el && !el.value.trim()) { el.classList.add('is-invalid'); valid = false; }
    else if (el) el.classList.remove('is-invalid');
  });

  const roomsPayload = [];
  let hasItem = false;

  Object.entries(rooms).forEach(([rk, room]) => {
    const nameInput = document.getElementById('room_name_' + rk);
    const roomName  = nameInput ? nameInput.value.trim() : room.name;
    if (!roomName) return;

    const itemsPayload = [];
    Object.values(room.items).forEach(item => {
      const p = _itemPayload(item);
      if (!p) return;
      itemsPayload.push(p);
      hasItem = true;
    });

    if (itemsPayload.length > 0) roomsPayload.push({ name: roomName, items: itemsPayload });
  });

  if (!hasItem) {
    showFormAlert('Please add at least one room with one complete item (name and size, or name, quantity and price).', 'warning');
    valid = false;
  }

  if (!valid) return false;
  document.getElementById('rooms_data_field').value = JSON.stringify(roomsPayload);
  return true;
}

function validateAndSubmit() {
  if (!_validateForm()) return false;
  return true;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function buildComboOptions(wood, work) {
  const combos = (CATALOG.combos || []).slice();
  const current = `${wood}|${work || ''}`;
  if (wood && !combos.some(c => c.value === current)) {          // e.g. a material hidden since: keep it
    combos.push({ value: current, label: comboLabel(wood, work) + ' (hidden)' });
  }
  return combos.map(c => {
    const sel = c.value === current ? 'selected' : '';
    return `<option value="${escHtml(c.value)}" ${sel}>${escHtml(c.label)}</option>`;
  }).join('');
}

// Stable soft colour for materials without a preset colour (custom ones like Glass, PU…)
const SOFT_COLORS = [['#dbeafe', '#1e3a8a'], ['#dcfce7', '#14532d'], ['#fef3c7', '#78350f'], ['#fce7f3', '#831843'],
                     ['#e0e7ff', '#312e81'], ['#ccfbf1', '#134e4a'], ['#fee2e2', '#7f1d1d'], ['#f3e8ff', '#581c87']];
function colorFor(key) {
  let h = 0;
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const [bg, color] = SOFT_COLORS[h % SOFT_COLORS.length];
  return { bg, color };
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function updateNoRoomsHint() {
  const hasRooms = Object.keys(rooms).length > 0;
  const hint = document.getElementById('no-rooms-hint');
  const addBtn = document.getElementById('add-room-btn-wrap');
  if (hint)   hint.style.display   = hasRooms ? 'none'  : 'block';
  if (addBtn) addBtn.style.display = hasRooms ? 'block' : 'none';
}

function showFormAlert(message, type) {
  const existing = document.getElementById('form-alert-dynamic');
  if (existing) existing.remove();
  const alert = document.createElement('div');
  alert.id = 'form-alert-dynamic';
  alert.className = `alert alert-${type || 'warning'} alert-dismissible fade show py-2 mt-2`;
  alert.innerHTML = `<i class="bi bi-exclamation-triangle me-2"></i>${message}
    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
  const form = document.getElementById('projectForm');
  if (form) form.prepend(alert);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
