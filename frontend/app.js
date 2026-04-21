'use strict';

// ============================================================
// CONFIG
// ============================================================
const API_BASE   = 'http://localhost:8080';
const PAGE_SIZE  = 12;

// ============================================================
// STATE
// ============================================================
const state = {
  token:         localStorage.getItem('dp_token') || null,
  user:          null,
  view:          'documents',
  docs:          [],
  notifications: [],
  unreadCount:   0,
  page:          0,
  activeTag:     null,
  darkMode:      localStorage.getItem('dp_dark') === 'true',
};

// ============================================================
// DARK MODE
// ============================================================
function applyTheme() {
  document.documentElement.setAttribute('data-theme', state.darkMode ? 'dark' : 'light');
  const icon = document.getElementById('dark-icon');
  if (icon) icon.textContent = state.darkMode ? '☀️' : '🌙';
}

function toggleDark() {
  state.darkMode = !state.darkMode;
  localStorage.setItem('dp_dark', state.darkMode);
  applyTheme();
}

// ============================================================
// API CLIENT
// ============================================================
async function apiFetch(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (state.token) headers['Authorization'] = `Bearer ${state.token}`;
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    throw new Error('Cannot reach the server. Is the API gateway running?');
  }
  if (res.status === 401) { doLogout(); return null; }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  if (res.status === 204) return null;
  return res.json();
}

const authAPI = {
  register: d  => apiFetch('/api/v1/auth/register', { method: 'POST', body: JSON.stringify(d) }),
  login:    d  => apiFetch('/api/v1/auth/login',    { method: 'POST', body: JSON.stringify(d) }),
  me:       () => apiFetch('/api/v1/auth/me'),
  logout:   () => apiFetch('/api/v1/auth/logout',   { method: 'POST' }),
};

const docsAPI = {
  list:      (skip = 0, limit = 500) => apiFetch(`/api/v1/documents?skip=${skip}&limit=${limit}`),
  get:       id         => apiFetch(`/api/v1/documents/${id}`),
  create:    d          => apiFetch('/api/v1/documents',              { method: 'POST', body: JSON.stringify(d) }),
  update:    (id, d)    => apiFetch(`/api/v1/documents/${id}`,        { method: 'PUT',  body: JSON.stringify(d) }),
  delete:    id         => apiFetch(`/api/v1/documents/${id}`,        { method: 'DELETE' }),
  search:    q          => apiFetch(`/api/v1/documents/search?q=${encodeURIComponent(q)}`),
  semantic:  (q, limit) => apiFetch('/api/v1/documents/search/semantic', {
    method: 'POST', body: JSON.stringify({ query: q, limit }),
  }),
  summarize:    (id, len) => apiFetch(`/api/v1/documents/${id}/summarize`, {
    method: 'POST', body: JSON.stringify({ max_length: len }),
  }),
  suggestTags:  id        => apiFetch(`/api/v1/documents/${id}/tags/suggest`, { method: 'POST' }),
};

const notifAPI = {
  list:     ownerId => apiFetch(`/api/v1/notifications${ownerId ? `?owner_id=${ownerId}` : ''}`),
  markRead: id      => apiFetch(`/api/v1/notifications/${id}/read`, { method: 'PUT' }),
};

// ============================================================
// TOAST
// ============================================================
function toast(message, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  document.getElementById('toasts').appendChild(el);
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add('visible')));
  setTimeout(() => { el.classList.remove('visible'); setTimeout(() => el.remove(), 300); }, 3800);
}

// ============================================================
// MODAL
// ============================================================
function openModal(title, bodyHTML, opts = {}) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHTML;
  document.getElementById('modal-backdrop').classList.remove('hidden');
  document.getElementById('modal').style.maxWidth = opts.wide ? '760px' : '';
}
function closeModal() {
  document.getElementById('modal-backdrop').classList.add('hidden');
}

// ============================================================
// UTILS
// ============================================================
function esc(str) {
  if (str == null) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function fmtDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-US', { year:'numeric', month:'short', day:'numeric' });
}
function fmtDateTime(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleString('en-US', {
    year:'numeric', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit',
  });
}
function tagsHTML(tags, clickable = false) {
  if (!tags || !tags.length) return '';
  return tags.map(t =>
    clickable
      ? `<span class="tag tag-clickable ${state.activeTag === t ? 'tag-active' : ''}"
             onclick="event.stopPropagation();setTagFilter('${esc(t)}')">${esc(t)}</span>`
      : `<span class="tag">${esc(t)}</span>`
  ).join('');
}
function setPageTitle(t) { document.getElementById('page-title').textContent = t; }
function setActiveNav(v) {
  document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === v));
}

// ============================================================
// SIDEBAR
// ============================================================
function openSidebar()  { document.getElementById('sidebar').classList.add('open'); document.getElementById('sidebar-overlay').classList.remove('hidden'); }
function closeSidebar() { document.getElementById('sidebar').classList.remove('open'); document.getElementById('sidebar-overlay').classList.add('hidden'); }

// ============================================================
// NAVIGATION
// ============================================================
function navigate(view) {
  state.view = view;
  closeSidebar();
  if (view === 'documents')     renderDocuments();
  else if (view === 'search')   renderSearch();
  else if (view === 'notifications') renderNotifications();
}

// ============================================================
// TAG FILTER
// ============================================================
function setTagFilter(tag) {
  state.activeTag = state.activeTag === tag ? null : tag;
  state.page = 0;
  renderTagBar();
  renderDocGrid();
}

function allTags() {
  return [...new Set(state.docs.flatMap(d => d.tags || []))].sort();
}

function filteredDocs() {
  if (!state.activeTag) return state.docs;
  return state.docs.filter(d => (d.tags || []).includes(state.activeTag));
}

function pagedDocs() {
  const start = state.page * PAGE_SIZE;
  return filteredDocs().slice(start, start + PAGE_SIZE);
}

function renderTagBar() {
  const bar = document.getElementById('tag-filter-bar');
  if (!bar) return;
  const tags = allTags();
  if (!tags.length) { bar.innerHTML = ''; return; }

  bar.innerHTML = `
    <button class="tag-filter-btn ${!state.activeTag ? 'active' : ''}"
            onclick="setTagFilter(null)">All</button>
    ${tags.map(t => `
      <button class="tag-filter-btn ${state.activeTag === t ? 'active' : ''}"
              onclick="setTagFilter('${esc(t)}')">${esc(t)}</button>
    `).join('')}
  `;
}

// ============================================================
// VIEW: DOCUMENTS
// ============================================================
async function renderDocuments() {
  setPageTitle('Documents');
  setActiveNav('documents');
  state.page      = 0;
  state.activeTag = null;

  document.getElementById('content').innerHTML = `
    <div class="view-header">
      <h2>My Documents</h2>
      <button class="btn btn-primary" id="new-doc-btn">+ New Document</button>
    </div>

    <div class="stats-bar">
      <div class="stat-card">
        <div class="stat-icon">📄</div>
        <div class="stat-info">
          <div class="stat-value" id="stat-total">—</div>
          <div class="stat-label">Total Documents</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">🏷️</div>
        <div class="stat-info">
          <div class="stat-value" id="stat-tags">—</div>
          <div class="stat-label">Unique Tags</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">🔔</div>
        <div class="stat-info">
          <div class="stat-value" id="stat-notifs">${state.unreadCount}</div>
          <div class="stat-label">Unread Alerts</div>
        </div>
      </div>
    </div>

    <div class="tag-filter-bar" id="tag-filter-bar"></div>

    <div class="doc-grid" id="doc-grid">
      <div class="loading">Loading documents…</div>
    </div>

    <div class="pagination hidden" id="pagination">
      <button class="btn btn-outline btn-sm" id="prev-btn" onclick="changePage(-1)">← Prev</button>
      <span class="page-info" id="page-info"></span>
      <button class="btn btn-outline btn-sm" id="next-btn" onclick="changePage(1)">Next →</button>
    </div>
  `;

  document.getElementById('new-doc-btn').onclick = () => showDocFormModal(null);

  try {
    const docs = await docsAPI.list(0, 500);
    state.docs = (docs || []).filter(d => !d.is_deleted);
    renderTagBar();
    renderDocGrid();
    updateDocStats();
  } catch (e) {
    document.getElementById('doc-grid').innerHTML = `<div class="error-state">${esc(e.message)}</div>`;
  }
}

function updateDocStats() {
  const total      = state.docs.length;
  const uniqueTags = new Set(state.docs.flatMap(d => d.tags || [])).size;
  const g = id => document.getElementById(id);
  if (g('stat-total'))  g('stat-total').textContent  = total;
  if (g('stat-tags'))   g('stat-tags').textContent   = uniqueTags;
  if (g('stat-notifs')) g('stat-notifs').textContent = state.unreadCount;
}

function changePage(dir) {
  const total = filteredDocs().length;
  const maxPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);
  state.page = Math.min(maxPage, Math.max(0, state.page + dir));
  renderDocGrid();
  document.getElementById('doc-grid')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderDocGrid() {
  const grid = document.getElementById('doc-grid');
  if (!grid) return;

  const visible = filteredDocs();
  const page    = pagedDocs();
  const totalPages = Math.ceil(visible.length / PAGE_SIZE);

  // Pagination controls
  const pag = document.getElementById('pagination');
  if (pag) {
    pag.classList.toggle('hidden', totalPages <= 1);
    const info = document.getElementById('page-info');
    if (info) info.textContent = `Page ${state.page + 1} of ${totalPages || 1} · ${visible.length} docs`;
    const prev = document.getElementById('prev-btn');
    const next = document.getElementById('next-btn');
    if (prev) prev.disabled = state.page === 0;
    if (next) next.disabled = state.page >= totalPages - 1;
  }

  if (!visible.length) {
    grid.innerHTML = state.activeTag
      ? `<div class="empty-state"><div class="empty-icon">🏷️</div>
           <h3>No documents with tag "${esc(state.activeTag)}"</h3>
           <p><button class="btn btn-outline btn-sm" onclick="setTagFilter(null)">Clear filter</button></p>
         </div>`
      : `<div class="empty-state"><div class="empty-icon">📄</div>
           <h3>No documents yet</h3><p>Create your first document to get started.</p>
         </div>`;
    return;
  }

  grid.innerHTML = page.map(doc => `
    <div class="doc-card" data-id="${esc(doc.id)}">
      <div class="doc-card-header">
        <h3 class="doc-title">${esc(doc.title)}</h3>
        <div class="doc-actions" onclick="event.stopPropagation()">
          <button class="btn-icon" title="View & Summarize" onclick="viewDocModal('${esc(doc.id)}')">👁</button>
          <button class="btn-icon" title="Edit"             onclick="showDocFormModal('${esc(doc.id)}')">✏️</button>
          <button class="btn-icon danger" title="Delete"    onclick="confirmDelete('${esc(doc.id)}')">🗑</button>
        </div>
      </div>
      <p class="doc-preview">${esc((doc.content || '').slice(0, 160))}${(doc.content || '').length > 160 ? '…' : ''}</p>
      <div class="doc-footer">
        <div class="doc-tags">${tagsHTML(doc.tags, true)}</div>
        <span class="doc-date">${fmtDate(doc.created_at)}</span>
      </div>
    </div>
  `).join('');

  grid.querySelectorAll('.doc-card').forEach(card => {
    card.addEventListener('click', () => viewDocModal(card.dataset.id));
  });
}

// ---- View Document Modal ----
async function viewDocModal(id) {
  openModal('Loading…', '<div class="loading-inline">Fetching document…</div>');
  try {
    const doc = await docsAPI.get(id);
    document.getElementById('modal-title').textContent = doc.title;
    document.getElementById('modal-body').innerHTML = `
      <div class="doc-view-tabs">
        <button class="tab-btn active" onclick="switchTab(this,'content')">Content</button>
        <button class="tab-btn"        onclick="switchTab(this,'summary')">AI Summary ⚡</button>
        <button class="tab-btn"        onclick="switchTab(this,'tags')">AI Tags 🏷</button>
      </div>

      <div id="tab-content" class="tab-pane">
        <div class="doc-content-full">${esc(doc.content || '')}</div>
        ${(doc.tags||[]).length ? `<div class="doc-view-tags mt-16">${tagsHTML(doc.tags)}</div>` : ''}
        <div class="text-light text-sm mt-16">
          Created ${fmtDateTime(doc.created_at)} · Updated ${fmtDateTime(doc.updated_at)}
        </div>
      </div>

      <div id="tab-summary" class="tab-pane hidden">
        <div class="summarize-controls">
          <label>Max length
            <input type="number" id="sum-len" value="150" min="50" max="500"
                   class="form-input form-input-sm" style="width:80px">
          </label>
          <button class="btn btn-primary btn-sm" onclick="runSummarize('${esc(id)}')">⚡ Generate</button>
        </div>
        <div id="summary-output"></div>
      </div>

      <div id="tab-tags" class="tab-pane hidden">
        <div class="summarize-controls">
          <span style="font-size:13px;color:var(--text-muted)">GPT suggests 3-6 tags based on your document content.</span>
          <button class="btn btn-primary btn-sm" onclick="runSuggestTags('${esc(id)}')">🏷 Suggest Tags</button>
        </div>
        <div id="tags-output"></div>
      </div>
    `;
  } catch (e) {
    document.getElementById('modal-body').innerHTML = `<div class="error-msg">${esc(e.message)}</div>`;
  }
}

function switchTab(btn, tab) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.add('hidden'));
  document.getElementById(`tab-${tab}`).classList.remove('hidden');
}

async function runSummarize(id) {
  const len = parseInt(document.getElementById('sum-len').value, 10) || 150;
  const out = document.getElementById('summary-output');
  out.innerHTML = '<div class="loading-inline">Generating summary…</div>';
  try {
    const res = await docsAPI.summarize(id, len);
    out.innerHTML = `
      <div class="summary-output">${esc(res.summary)}</div>
      <div class="summary-meta">
        <span>Model: <strong>${esc(res.model_used)}</strong></span>
        <span>Original: <strong>${res.original_length}</strong> chars</span>
        <span>Summary: <strong>${res.summary_length}</strong> chars</span>
      </div>
    `;
  } catch (e) {
    out.innerHTML = `<div class="error-msg">${esc(e.message)}</div>`;
  }
}

async function runSuggestTags(id) {
  const out = document.getElementById('tags-output');
  out.innerHTML = '<div class="loading-inline">Asking AI for tag suggestions…</div>';
  try {
    const res = await docsAPI.suggestTags(id);
    if (!res.suggested_tags || res.suggested_tags.length === 0) {
      out.innerHTML = '<div class="text-muted text-sm">No tags suggested (OpenAI key may not be configured).</div>';
      return;
    }
    out.innerHTML = `
      <div style="margin-top:12px">
        <div style="font-size:13px;color:var(--text-muted);margin-bottom:10px">
          Suggested by <strong>${esc(res.model_used)}</strong> — click to apply:
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">
          ${res.suggested_tags.map(t => `
            <button class="tag tag-clickable" style="font-size:13px;padding:5px 14px;cursor:pointer"
                    onclick="applyTagToDoc('${esc(id)}', '${esc(t)}', this)">${esc(t)}</button>
          `).join('')}
        </div>
        <div id="tag-apply-status" style="font-size:13px;color:var(--success)"></div>
      </div>
    `;
  } catch (e) {
    out.innerHTML = `<div class="error-msg">${esc(e.message)}</div>`;
  }
}

async function applyTagToDoc(id, tag, btn) {
  const doc = state.docs.find(d => d.id === id);
  if (!doc) return;
  const existing = doc.tags || [];
  if (existing.includes(tag)) {
    document.getElementById('tag-apply-status').textContent = `"${tag}" is already on this document.`;
    return;
  }
  try {
    btn.disabled = true;
    const updated = await docsAPI.update(id, { tags: [...existing, tag] });
    const idx = state.docs.findIndex(d => d.id === id);
    if (idx !== -1) state.docs[idx] = updated;
    btn.classList.add('tag-active');
    document.getElementById('tag-apply-status').textContent = `✓ "${tag}" added to document.`;
    renderTagBar();
    renderDocGrid();
  } catch (e) {
    document.getElementById('tag-apply-status').textContent = `Error: ${e.message}`;
    btn.disabled = false;
  }
}

// ---- Create / Edit Document Modal ----
let _draftTimer = null;
const DRAFT_KEY = 'dp_draft';

function showDocFormModal(id) {
  const doc   = id ? state.docs.find(d => d.id === id) : null;
  const draft = !id ? JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null') : null;

  openModal(doc ? 'Edit Document' : 'New Document', `
    <form id="doc-form" class="form-stack" onsubmit="return false">
      <div class="form-group">
        <label for="f-title">Title <span style="color:var(--danger)">*</span></label>
        <input id="f-title" type="text" class="form-input" required
               value="${doc ? esc(doc.title) : esc(draft?.title || '')}"
               placeholder="Document title">
      </div>
      <div class="form-group">
        <label for="f-content">
          Content <span style="color:var(--danger)">*</span>
          ${draft && !id ? '<span class="draft-badge">Draft restored</span>' : ''}
        </label>
        <div class="editor-wrap">
          <textarea id="f-content" class="form-textarea editor-textarea" required
                    placeholder="Write your document content here…"
                    rows="11">${doc ? esc(doc.content || '') : esc(draft?.content || '')}</textarea>
          <div class="editor-meta">
            <span id="word-count">0 words</span>
            <span id="char-count">0 / 50,000 chars</span>
            <span id="draft-saved" class="draft-saved-indicator hidden">✓ Draft saved</span>
          </div>
        </div>
      </div>
      <div class="form-group">
        <label for="f-tags">Tags <span class="label-hint">(comma-separated)</span></label>
        <input id="f-tags" type="text" class="form-input"
               value="${doc ? esc((doc.tags||[]).join(', ')) : esc(draft?.tags || '')}"
               placeholder="e.g. report, finance, 2024">
      </div>
      <div class="form-actions">
        ${!id ? '<button type="button" class="btn btn-ghost btn-sm" onclick="clearDraft()">Clear draft</button>' : ''}
        <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
        <button type="button" class="btn btn-primary" id="doc-submit-btn"
                onclick="submitDocForm('${id || ''}')">
          ${doc ? 'Update' : 'Create Document'}
        </button>
      </div>
    </form>
  `, { wide: true });

  // Wire up live word/char count + draft auto-save
  const textarea = document.getElementById('f-content');
  if (textarea) {
    updateEditorMeta(textarea);
    textarea.addEventListener('input', () => {
      updateEditorMeta(textarea);
      if (!id) scheduleDraftSave();
    });
    textarea.focus();
  }
}

function updateEditorMeta(textarea) {
  const text   = textarea.value;
  const words  = text.trim() ? text.trim().split(/\s+/).length : 0;
  const chars  = text.length;
  const wEl = document.getElementById('word-count');
  const cEl = document.getElementById('char-count');
  if (wEl) wEl.textContent = `${words.toLocaleString()} word${words !== 1 ? 's' : ''}`;
  if (cEl) {
    cEl.textContent = `${chars.toLocaleString()} / 50,000 chars`;
    cEl.style.color = chars > 45000 ? 'var(--danger)' : '';
  }
}

function scheduleDraftSave() {
  clearTimeout(_draftTimer);
  _draftTimer = setTimeout(() => {
    const title   = document.getElementById('f-title')?.value || '';
    const content = document.getElementById('f-content')?.value || '';
    const tags    = document.getElementById('f-tags')?.value || '';
    if (content.trim()) {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ title, content, tags }));
      const ind = document.getElementById('draft-saved');
      if (ind) { ind.classList.remove('hidden'); setTimeout(() => ind.classList.add('hidden'), 2000); }
    }
  }, 1000);
}

function clearDraft() {
  localStorage.removeItem(DRAFT_KEY);
  const f = document.getElementById('f-title');
  const c = document.getElementById('f-content');
  const t = document.getElementById('f-tags');
  if (f) f.value = '';
  if (c) { c.value = ''; updateEditorMeta(c); }
  if (t) t.value = '';
  toast('Draft cleared', 'info');
}

async function submitDocForm(id) {
  clearTimeout(_draftTimer);
  const titleEl   = document.getElementById('f-title');
  const contentEl = document.getElementById('f-content');
  const tagsEl    = document.getElementById('f-tags');
  const submitBtn = document.getElementById('doc-submit-btn');

  if (!titleEl.value.trim())   { toast('Title is required', 'error');   titleEl.focus();   return; }
  if (!contentEl.value.trim()) { toast('Content is required', 'error'); contentEl.focus(); return; }

  const payload = {
    title:   titleEl.value.trim(),
    content: contentEl.value.trim(),
    tags:    tagsEl.value.split(',').map(t => t.trim()).filter(Boolean),
  };

  submitBtn.disabled    = true;
  submitBtn.textContent = id ? 'Updating…' : 'Creating…';

  try {
    if (id) {
      const updated = await docsAPI.update(id, payload);
      const idx = state.docs.findIndex(d => d.id === id);
      if (idx !== -1) state.docs[idx] = updated;
      toast('Document updated', 'success');
    } else {
      const created = await docsAPI.create(payload);
      state.docs.unshift(created);
      localStorage.removeItem(DRAFT_KEY);
      toast('Document created', 'success');
    }
    closeModal();
    renderTagBar();
    renderDocGrid();
    updateDocStats();
  } catch (e) {
    toast(e.message, 'error');
    submitBtn.disabled    = false;
    submitBtn.textContent = id ? 'Update' : 'Create Document';
  }
}

async function confirmDelete(id) {
  const doc  = state.docs.find(d => d.id === id);
  const name = doc ? `"${doc.title}"` : 'this document';
  if (!confirm(`Delete ${name}? This cannot be undone.`)) return;
  try {
    await docsAPI.delete(id);
    state.docs = state.docs.filter(d => d.id !== id);
    if (state.activeTag && !state.docs.some(d => (d.tags||[]).includes(state.activeTag)))
      state.activeTag = null;
    renderTagBar();
    renderDocGrid();
    updateDocStats();
    toast('Document deleted', 'success');
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ============================================================
// VIEW: SEARCH
// ============================================================
let searchMode = 'keyword';

function renderSearch() {
  setPageTitle('Search');
  setActiveNav('search');

  document.getElementById('content').innerHTML = `
    <div class="search-container">
      <div class="view-header"><h2>Search Documents</h2></div>

      <div class="search-mode-toggle">
        <button class="mode-btn active" onclick="setSearchMode(this,'keyword')">Keyword</button>
        <button class="mode-btn"        onclick="setSearchMode(this,'semantic')">Semantic AI ⚡</button>
      </div>

      <div class="search-input-row">
        <input id="search-q" type="text" class="form-input"
               placeholder="Enter your search query…" autocomplete="off">
        <button class="btn btn-primary" onclick="doSearch()">Search</button>
      </div>
      <div id="semantic-opts" class="search-limit-row hidden">
        <label>Results:
          <input id="sem-limit" type="number" value="5" min="1" max="50"
                 class="form-input form-input-sm" style="width:64px">
        </label>
      </div>
      <div id="search-results" class="search-results"></div>
    </div>
  `;

  document.getElementById('search-q').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
  searchMode = 'keyword';
}

function setSearchMode(btn, mode) {
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  searchMode = mode;
  document.getElementById('semantic-opts')?.classList.toggle('hidden', mode !== 'semantic');
}

async function doSearch() {
  const query     = (document.getElementById('search-q')?.value || '').trim();
  const resultsEl = document.getElementById('search-results');
  if (!query) { toast('Enter a search query', 'warning'); return; }
  resultsEl.innerHTML = '<div class="loading">Searching…</div>';
  try {
    if (searchMode === 'semantic') {
      const limit   = parseInt(document.getElementById('sem-limit')?.value, 10) || 5;
      const results = await docsAPI.semantic(query, limit);
      renderSearchResults(results, true);
    } else {
      const results = await docsAPI.search(query);
      renderSearchResults(results, false);
    }
  } catch (e) {
    resultsEl.innerHTML = `<div class="error-state">${esc(e.message)}</div>`;
  }
}

function renderSearchResults(results, isSemantic) {
  const resultsEl = document.getElementById('search-results');
  if (!results || !results.length) {
    resultsEl.innerHTML = `
      <div class="empty-state" style="padding:40px 0">
        <div class="empty-icon">🔍</div>
        <h3>No results found</h3>
        <p>Try different keywords or switch to ${isSemantic ? 'keyword' : 'semantic AI'} search.</p>
      </div>`;
    return;
  }
  const cards = results.map(doc => `
    <div class="doc-card" onclick="viewDocModal('${esc(doc.id)}')">
      <div class="doc-card-header">
        <h3 class="doc-title">${esc(doc.title)}</h3>
        ${isSemantic ? `<span class="score-badge">${((doc.similarity_score||0)*100).toFixed(0)}%</span>` : ''}
      </div>
      <p class="doc-preview">${esc((doc.content||'').slice(0,180))}…</p>
      <div class="doc-footer"><div class="doc-tags">${tagsHTML(doc.tags)}</div></div>
    </div>`).join('');

  resultsEl.innerHTML = `
    <div class="results-meta">
      <strong>${results.length}</strong> result${results.length!==1?'s':''} found
      ${isSemantic ? '· ranked by semantic similarity' : ''}
    </div>
    <div class="doc-grid">${cards}</div>`;
}

// ============================================================
// VIEW: NOTIFICATIONS
// ============================================================
async function renderNotifications() {
  setPageTitle('Notifications');
  setActiveNav('notifications');
  document.getElementById('content').innerHTML = `
    <div class="view-header">
      <h2>Notifications</h2>
      <button class="btn btn-outline btn-sm" onclick="markAllRead()">✓ Mark all read</button>
    </div>
    <div class="notif-list" id="notif-list"><div class="loading">Loading…</div></div>
  `;
  await loadNotifications();
}

async function loadNotifications() {
  try {
    const notifs        = await notifAPI.list(state.user?.id || null);
    state.notifications = notifs || [];
    state.unreadCount   = state.notifications.filter(n => !n.is_read).length;
    updateNotifBadge();
    renderNotifList();
  } catch (e) {
    const el = document.getElementById('notif-list');
    if (el) el.innerHTML = `<div class="error-state">${esc(e.message)}</div>`;
  }
}

function renderNotifList() {
  const el = document.getElementById('notif-list');
  if (!el) return;
  if (!state.notifications.length) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">🔔</div>
      <h3>No notifications yet</h3><p>Document events will appear here.</p></div>`;
    return;
  }
  el.innerHTML = state.notifications.map(n => `
    <div class="notif-item ${n.is_read ? '' : 'unread'}">
      <div class="notif-indicator"></div>
      <div class="notif-body">
        <div class="notif-message">${esc(n.message)}</div>
        <div class="notif-meta">
          <span class="notif-type">${esc(n.event_type)}</span>
          <span>${fmtDateTime(n.created_at)}</span>
        </div>
      </div>
      ${!n.is_read
        ? `<button class="btn-icon" title="Mark as read" onclick="markRead('${esc(n.id)}')">✓</button>`
        : ''}
    </div>`).join('');
}

async function markRead(id) {
  try {
    await notifAPI.markRead(id);
    const n = state.notifications.find(n => n.id === id);
    if (n) n.is_read = true;
    state.unreadCount = Math.max(0, state.unreadCount - 1);
    updateNotifBadge();
    renderNotifList();
  } catch (e) { toast(e.message, 'error'); }
}

async function markAllRead() {
  const unread = state.notifications.filter(n => !n.is_read);
  if (!unread.length) { toast('All notifications already read', 'info'); return; }
  for (const n of unread) { await notifAPI.markRead(n.id).catch(()=>{}); n.is_read = true; }
  state.unreadCount = 0;
  updateNotifBadge();
  renderNotifList();
  toast('All marked as read', 'success');
}

function updateNotifBadge() {
  const badge = document.getElementById('notif-badge');
  if (!badge) return;
  badge.textContent = state.unreadCount;
  badge.classList.toggle('hidden', state.unreadCount === 0);
}

// ============================================================
// AUTH
// ============================================================
async function doLogin(email, password) {
  const data  = await authAPI.login({ email, password });
  state.token = data.access_token;
  localStorage.setItem('dp_token', state.token);
}

async function doRegister(email, password, fullName) {
  await authAPI.register({ email, password, full_name: fullName });
}

async function loadUser() {
  state.user = await authAPI.me();
  const name    = state.user.full_name || state.user.email;
  const initial = (name || 'U')[0].toUpperCase();
  document.getElementById('header-user').textContent = name;
  const sn = document.getElementById('sidebar-user-name');
  const sr = document.getElementById('sidebar-user-role');
  const av = document.getElementById('sidebar-avatar');
  if (sn) sn.textContent = name;
  if (sr) sr.textContent = state.user.role || 'user';
  if (av) av.textContent = initial;
}

function doLogout() {
  authAPI.logout().catch(()=>{});
  state.token = null; state.user = null;
  state.docs = []; state.notifications = []; state.unreadCount = 0;
  localStorage.removeItem('dp_token');
  showAuth();
}

function showAuth() {
  document.getElementById('auth-screen').classList.remove('hidden');
  document.getElementById('app-shell').classList.add('hidden');
}
function showApp() {
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app-shell').classList.remove('hidden');
}

// ============================================================
// AUTH FORMS
// ============================================================
function setupAuthForms() {
  document.querySelectorAll('.auth-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const target = tab.dataset.tab;
      document.getElementById('login-form').classList.toggle('hidden',    target !== 'login');
      document.getElementById('register-form').classList.toggle('hidden', target !== 'register');
    });
  });

  document.getElementById('login-form').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = e.target.querySelector('[type=submit]');
    btn.disabled = true; btn.textContent = 'Signing in…';
    try {
      await doLogin(e.target.email.value, e.target.password.value);
      await loadUser();
      showApp();
      loadNotifications().catch(()=>{});
      navigate('documents');
    } catch (err) {
      toast(err.message, 'error');
      btn.disabled = false; btn.textContent = 'Sign In';
    }
  });

  document.getElementById('register-form').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = e.target.querySelector('[type=submit]');
    if (e.target.password.value !== e.target.password2.value) { toast('Passwords do not match', 'error'); return; }
    btn.disabled = true; btn.textContent = 'Creating account…';
    try {
      await doRegister(e.target.email.value, e.target.password.value, e.target.full_name.value);
      toast('Account created! Please sign in.', 'success');
      document.querySelector('.auth-tab[data-tab="login"]').click();
      document.getElementById('login-email').value = e.target.email.value;
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      btn.disabled = false; btn.textContent = 'Create Account';
    }
  });
}

// ============================================================
// BOOT
// ============================================================
async function init() {
  applyTheme();
  setupAuthForms();

  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', e => { e.preventDefault(); navigate(item.dataset.view); });
  });

  document.getElementById('hamburger').addEventListener('click', openSidebar);
  document.getElementById('sidebar-close').addEventListener('click', closeSidebar);
  document.getElementById('sidebar-overlay').addEventListener('click', closeSidebar);
  document.getElementById('modal-close').addEventListener('click', closeModal);
  document.getElementById('modal-backdrop').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeModal();
  });
  document.getElementById('logout-btn').addEventListener('click', doLogout);
  document.getElementById('dark-toggle')?.addEventListener('click', toggleDark);

  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

  if (state.token) {
    try {
      await loadUser();
      showApp();
      loadNotifications().catch(()=>{});
      navigate('documents');
      return;
    } catch {
      localStorage.removeItem('dp_token');
      state.token = null;
    }
  }
  showAuth();
}

document.addEventListener('DOMContentLoaded', init);
