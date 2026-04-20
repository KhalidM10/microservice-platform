'use strict';

// ============================================================
// CONFIG
// ============================================================
const API_BASE = 'http://localhost:8080';

// ============================================================
// STATE
// ============================================================
const state = {
  token:        localStorage.getItem('dp_token') || null,
  user:         null,
  view:         'documents',
  docs:         [],
  notifications:[],
  unreadCount:  0,
};

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

  if (res.status === 401) {
    doLogout();
    return null;
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  if (res.status === 204) return null;
  return res.json();
}

const authAPI = {
  register: (d)  => apiFetch('/api/v1/auth/register', { method: 'POST', body: JSON.stringify(d) }),
  login:    (d)  => apiFetch('/api/v1/auth/login',    { method: 'POST', body: JSON.stringify(d) }),
  me:       ()   => apiFetch('/api/v1/auth/me'),
  logout:   ()   => apiFetch('/api/v1/auth/logout',   { method: 'POST' }),
};

const docsAPI = {
  list:     (skip = 0, limit = 50) =>
    apiFetch(`/api/v1/documents?skip=${skip}&limit=${limit}`),
  get:      (id)       => apiFetch(`/api/v1/documents/${id}`),
  create:   (d)        => apiFetch('/api/v1/documents',              { method: 'POST', body: JSON.stringify(d) }),
  update:   (id, d)    => apiFetch(`/api/v1/documents/${id}`,        { method: 'PUT',  body: JSON.stringify(d) }),
  delete:   (id)       => apiFetch(`/api/v1/documents/${id}`,        { method: 'DELETE' }),
  search:   (q)        => apiFetch(`/api/v1/documents/search?q=${encodeURIComponent(q)}`),
  semantic: (q, limit) => apiFetch('/api/v1/documents/search/semantic', {
    method: 'POST', body: JSON.stringify({ query: q, limit }),
  }),
  summarize:(id, len)  => apiFetch(`/api/v1/documents/${id}/summarize`, {
    method: 'POST', body: JSON.stringify({ max_length: len }),
  }),
};

const notifAPI = {
  list:     (ownerId) => apiFetch(`/api/v1/notifications${ownerId ? `?owner_id=${ownerId}` : ''}`),
  markRead: (id)      => apiFetch(`/api/v1/notifications/${id}/read`, { method: 'PUT' }),
};

// ============================================================
// TOAST
// ============================================================
function toast(message, type = 'info') {
  const container = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  container.appendChild(el);
  requestAnimationFrame(() => {
    requestAnimationFrame(() => el.classList.add('visible'));
  });
  setTimeout(() => {
    el.classList.remove('visible');
    setTimeout(() => el.remove(), 300);
  }, 3800);
}

// ============================================================
// MODAL
// ============================================================
function openModal(title, bodyHTML, opts = {}) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHTML;
  document.getElementById('modal-backdrop').classList.remove('hidden');
  if (opts.wide) document.getElementById('modal').style.maxWidth = '760px';
  else document.getElementById('modal').style.maxWidth = '';
}

function closeModal() {
  document.getElementById('modal-backdrop').classList.add('hidden');
}

// ============================================================
// UTILS
// ============================================================
function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

function fmtDateTime(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function tagsHTML(tags) {
  if (!tags || !tags.length) return '';
  return tags.map(t => `<span class="tag">${esc(t)}</span>`).join('');
}

function setPageTitle(title) {
  document.getElementById('page-title').textContent = title;
}

function setActiveNav(view) {
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.view === view);
  });
}

// ============================================================
// SIDEBAR (mobile)
// ============================================================
function openSidebar() {
  document.getElementById('sidebar').classList.add('open');
  document.getElementById('sidebar-overlay').classList.remove('hidden');
}
function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebar-overlay').classList.add('hidden');
}

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
// VIEW: DOCUMENTS
// ============================================================
async function renderDocuments() {
  setPageTitle('Documents');
  setActiveNav('documents');

  document.getElementById('content').innerHTML = `
    <div class="view-header">
      <h2>My Documents</h2>
      <button class="btn btn-primary" id="new-doc-btn">+ New Document</button>
    </div>
    <div class="stats-bar" id="stats-bar">
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
          <div class="stat-label">Unread Notifications</div>
        </div>
      </div>
    </div>
    <div class="doc-grid" id="doc-grid">
      <div class="loading">Loading documents…</div>
    </div>
  `;

  document.getElementById('new-doc-btn').onclick = () => showDocFormModal(null);

  try {
    const docs = await docsAPI.list(0, 100);
    state.docs = (docs || []).filter(d => !d.is_deleted);
    renderDocGrid();
    updateDocStats();
  } catch (e) {
    document.getElementById('doc-grid').innerHTML =
      `<div class="error-state">${esc(e.message)}</div>`;
  }
}

function updateDocStats() {
  const total = state.docs.length;
  const allTags = state.docs.flatMap(d => d.tags || []);
  const uniqueTags = new Set(allTags).size;
  const el = id => document.getElementById(id);
  if (el('stat-total')) el('stat-total').textContent = total;
  if (el('stat-tags'))  el('stat-tags').textContent  = uniqueTags;
  if (el('stat-notifs')) el('stat-notifs').textContent = state.unreadCount;
}

function renderDocGrid() {
  const grid = document.getElementById('doc-grid');
  if (!grid) return;

  if (!state.docs.length) {
    grid.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📄</div>
        <h3>No documents yet</h3>
        <p>Create your first document to get started.</p>
      </div>
    `;
    return;
  }

  grid.innerHTML = state.docs.map(doc => `
    <div class="doc-card" data-id="${esc(doc.id)}">
      <div class="doc-card-header">
        <h3 class="doc-title">${esc(doc.title)}</h3>
        <div class="doc-actions" onclick="event.stopPropagation()">
          <button class="btn-icon" title="View & Summarize" onclick="viewDocModal('${esc(doc.id)}')">👁</button>
          <button class="btn-icon" title="Edit" onclick="showDocFormModal('${esc(doc.id)}')">✏️</button>
          <button class="btn-icon danger" title="Delete" onclick="confirmDelete('${esc(doc.id)}')">🗑</button>
        </div>
      </div>
      <p class="doc-preview">${esc((doc.content || '').slice(0, 160))}${(doc.content || '').length > 160 ? '…' : ''}</p>
      <div class="doc-footer">
        <div class="doc-tags">${tagsHTML(doc.tags)}</div>
        <span class="doc-date">${fmtDate(doc.created_at)}</span>
      </div>
    </div>
  `).join('');

  // Open view on card click (not on action buttons)
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
        <button class="tab-btn" onclick="switchTab(this,'summary')">AI Summary</button>
      </div>

      <div id="tab-content" class="tab-pane">
        <div class="doc-content-full">${esc(doc.content || '')}</div>
        ${(doc.tags||[]).length ? `<div class="doc-view-tags">${tagsHTML(doc.tags)}</div>` : ''}
        <div class="text-light text-sm mt-16">
          Created ${fmtDateTime(doc.created_at)} · Updated ${fmtDateTime(doc.updated_at)}
        </div>
      </div>

      <div id="tab-summary" class="tab-pane hidden">
        <div class="summarize-controls">
          <label>
            Max length
            <input type="number" id="sum-len" value="150" min="50" max="500"
                   class="form-input form-input-sm" style="width:80px">
          </label>
          <button class="btn btn-primary btn-sm" onclick="runSummarize('${esc(id)}')">
            ⚡ Generate Summary
          </button>
        </div>
        <div id="summary-output"></div>
      </div>
    `;
  } catch (e) {
    document.getElementById('modal-body').innerHTML =
      `<div class="error-msg">${esc(e.message)}</div>`;
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

// ---- Create / Edit Document Modal ----
function showDocFormModal(id) {
  const doc = id ? state.docs.find(d => d.id === id) : null;
  const title = doc ? 'Edit Document' : 'New Document';

  openModal(title, `
    <form id="doc-form" class="form-stack" onsubmit="return false">
      <div class="form-group">
        <label for="f-title">Title <span style="color:var(--danger)">*</span></label>
        <input id="f-title" type="text" class="form-input" required
               value="${doc ? esc(doc.title) : ''}" placeholder="Document title">
      </div>
      <div class="form-group">
        <label for="f-content">Content <span style="color:var(--danger)">*</span></label>
        <textarea id="f-content" class="form-textarea" required
                  placeholder="Write your document content here…" rows="9">${doc ? esc(doc.content || '') : ''}</textarea>
      </div>
      <div class="form-group">
        <label for="f-tags">Tags <span class="label-hint">(comma-separated)</span></label>
        <input id="f-tags" type="text" class="form-input"
               value="${doc ? (doc.tags || []).join(', ') : ''}"
               placeholder="e.g. report, finance, 2024">
      </div>
      <div class="form-actions">
        <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
        <button type="button" class="btn btn-primary" id="doc-submit-btn"
                onclick="submitDocForm('${id || ''}')">
          ${doc ? 'Update' : 'Create Document'}
        </button>
      </div>
    </form>
  `, { wide: true });
}

async function submitDocForm(id) {
  const titleEl   = document.getElementById('f-title');
  const contentEl = document.getElementById('f-content');
  const tagsEl    = document.getElementById('f-tags');
  const submitBtn = document.getElementById('doc-submit-btn');

  if (!titleEl.value.trim())   { toast('Title is required', 'error'); titleEl.focus(); return; }
  if (!contentEl.value.trim()) { toast('Content is required', 'error'); contentEl.focus(); return; }

  const payload = {
    title:   titleEl.value.trim(),
    content: contentEl.value.trim(),
    tags:    tagsEl.value.split(',').map(t => t.trim()).filter(Boolean),
  };

  submitBtn.disabled = true;
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
      toast('Document created', 'success');
    }
    closeModal();
    renderDocGrid();
    updateDocStats();
  } catch (e) {
    toast(e.message, 'error');
    submitBtn.disabled = false;
    submitBtn.textContent = id ? 'Update' : 'Create Document';
  }
}

async function confirmDelete(id) {
  const doc = state.docs.find(d => d.id === id);
  const name = doc ? `"${doc.title}"` : 'this document';
  if (!confirm(`Delete ${name}? This cannot be undone.`)) return;
  try {
    await docsAPI.delete(id);
    state.docs = state.docs.filter(d => d.id !== id);
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
      <div class="view-header">
        <h2>Search Documents</h2>
      </div>

      <div class="search-mode-toggle">
        <button class="mode-btn active" onclick="setSearchMode(this,'keyword')">Keyword Search</button>
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

  document.getElementById('search-q').addEventListener('keydown', e => {
    if (e.key === 'Enter') doSearch();
  });
  searchMode = 'keyword';
}

function setSearchMode(btn, mode) {
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  searchMode = mode;
  const opts = document.getElementById('semantic-opts');
  if (opts) opts.classList.toggle('hidden', mode !== 'semantic');
}

async function doSearch() {
  const query = (document.getElementById('search-q')?.value || '').trim();
  const resultsEl = document.getElementById('search-results');
  if (!query) { toast('Enter a search query', 'warning'); return; }

  resultsEl.innerHTML = '<div class="loading">Searching…</div>';

  try {
    let results;
    if (searchMode === 'semantic') {
      const limit = parseInt(document.getElementById('sem-limit')?.value, 10) || 5;
      results = await docsAPI.semantic(query, limit);
      renderSearchResults(results, true);
    } else {
      results = await docsAPI.search(query);
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
        <p>Try different keywords or switch to ${isSemantic ? 'keyword' : 'semantic'} search.</p>
      </div>
    `;
    return;
  }

  const cards = results.map(doc => {
    const score = isSemantic
      ? `<span class="score-badge">${((doc.similarity_score || 0) * 100).toFixed(0)}% match</span>`
      : '';
    return `
      <div class="doc-card" onclick="viewDocModal('${esc(doc.id)}')">
        <div class="doc-card-header">
          <h3 class="doc-title">${esc(doc.title)}</h3>
          ${score}
        </div>
        <p class="doc-preview">${esc((doc.content || '').slice(0, 180))}…</p>
        <div class="doc-footer">
          <div class="doc-tags">${tagsHTML(doc.tags)}</div>
        </div>
      </div>
    `;
  });

  resultsEl.innerHTML = `
    <div class="results-meta">
      <strong>${results.length}</strong> result${results.length !== 1 ? 's' : ''} found
      ${isSemantic ? '· sorted by semantic similarity' : ''}
    </div>
    <div class="doc-grid">${cards.join('')}</div>
  `;
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
    <div class="notif-list" id="notif-list">
      <div class="loading">Loading…</div>
    </div>
  `;

  await loadNotifications();
}

async function loadNotifications() {
  try {
    const ownerId = state.user?.id || null;
    const notifs = await notifAPI.list(ownerId);
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
    el.innerHTML = `
      <div class="empty-state" style="grid-column:1/-1">
        <div class="empty-icon">🔔</div>
        <h3>No notifications yet</h3>
        <p>Document events will appear here automatically.</p>
      </div>
    `;
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
    </div>
  `).join('');
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
  if (!unread.length) { toast('All notifications are already read', 'info'); return; }
  for (const n of unread) {
    await notifAPI.markRead(n.id).catch(() => {});
    n.is_read = true;
  }
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
  const data = await authAPI.login({ email, password });
  state.token = data.access_token;
  localStorage.setItem('dp_token', state.token);
}

async function doRegister(email, password, fullName) {
  await authAPI.register({ email, password, full_name: fullName });
}

async function loadUser() {
  state.user = await authAPI.me();
  const name = state.user.full_name || state.user.email;
  const initial = (state.user.full_name || state.user.email || 'U')[0].toUpperCase();

  document.getElementById('header-user').textContent = name;

  const sidebarName = document.getElementById('sidebar-user-name');
  const sidebarRole = document.getElementById('sidebar-user-role');
  const avatarEl    = document.getElementById('sidebar-avatar');
  if (sidebarName) sidebarName.textContent = name;
  if (sidebarRole) sidebarRole.textContent = state.user.role || 'user';
  if (avatarEl)    avatarEl.textContent    = initial;
}

function doLogout() {
  authAPI.logout().catch(() => {});
  state.token         = null;
  state.user          = null;
  state.docs          = [];
  state.notifications = [];
  state.unreadCount   = 0;
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
// AUTH FORM HANDLERS
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

  // Login
  document.getElementById('login-form').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = e.target.querySelector('[type=submit]');
    btn.disabled = true;
    btn.textContent = 'Signing in…';
    try {
      await doLogin(e.target.email.value, e.target.password.value);
      await loadUser();
      showApp();
      loadNotifications().catch(() => {});
      navigate('documents');
    } catch (err) {
      toast(err.message, 'error');
      btn.disabled = false;
      btn.textContent = 'Sign In';
    }
  });

  // Register
  document.getElementById('register-form').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = e.target.querySelector('[type=submit]');
    if (e.target.password.value !== e.target.password2.value) {
      toast('Passwords do not match', 'error');
      return;
    }
    btn.disabled = true;
    btn.textContent = 'Creating account…';
    try {
      await doRegister(e.target.email.value, e.target.password.value, e.target.full_name.value);
      toast('Account created! Please sign in.', 'success');
      document.querySelector('.auth-tab[data-tab="login"]').click();
      document.getElementById('login-email').value = e.target.email.value;
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Create Account';
    }
  });
}

// ============================================================
// BOOT
// ============================================================
async function init() {
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

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });

  if (state.token) {
    try {
      await loadUser();
      showApp();
      loadNotifications().catch(() => {});
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
