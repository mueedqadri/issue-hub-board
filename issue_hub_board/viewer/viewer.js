// Read-only issue viewer: everything lives in memory, so filters, search and
// navigation never wait on the network. The last index is cached locally and
// drawn first; a background check swaps in a newer one.
(() => {
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};
const KEY = 'issue-viewer:' + location.pathname.replace(/[^/]*$/, '');
const THEME_KEY = 'issue-hub-theme';
const HUB_SLUG = decodeURIComponent(location.pathname.replace(/\/[^/]*$/, '').split('/').pop() || '');
let HUBS = [];
const ID_RE = /\b([A-Z][A-Z0-9]*-\d+)\b/g;
const now = () => performance.now();
const timings = (window.__viewerTimings = []);

const VIEWS = {
  active: { name: 'Active', statuses: ['In Progress', 'In Review', 'Todo'] },
  backlog: { name: 'Backlog', statuses: ['Backlog'] },
  all: { name: 'All issues', statuses: null },
  done: { name: 'Done', statuses: ['Done', 'Canceled'] },
};
const STATUS_ORDER = ['In Progress', 'In Review', 'Todo', 'Backlog', 'Done', 'Canceled'];
const PRI_RANK = { 1: 0, 2: 1, 3: 2, 4: 3, 0: 4 };
const KIND_HUES = { Bug: 4, Feature: 145, Improvement: 212, Task: 38 };
const FIELDS = ['status', 'priority', 'kind', 'label', 'project'];
const GROUPS = { status: 'Status', project: 'Project', kind: 'Kind', priority: 'Priority', none: 'No grouping' };
const ORDERS = { priority: 'Priority', updated: 'Last updated', created: 'Created', number: 'Number' };
const PROJECT_DONE = ['Completed', 'Canceled', 'Done'];

let D = null;
let byId = new Map();
let projects = new Map();
let labelGroup = new Map();
let labelHue = new Map();
let lastModified = null;
let S = {};
let order = [];
let sel = null;
let expanded = new Set();
let closed = new Set(JSON.parse(store.get(KEY + ':closed') || '[]'));
const pages = new Map();

// ---------------------------------------------------------------- state and URL

function parseHash() {
  const raw = decodeURIComponent(location.hash.slice(1));
  const legacy = raw.match(/^([A-Z][A-Z0-9]*-\d+)$/);
  if (legacy) return { ...defaults(), issue: legacy[1] };
  const [path, query = ''] = location.hash.slice(1).split('?');
  const parts = path.replace(/^\//, '').split('/').map(decodeURIComponent);
  const p = new URLSearchParams(query);
  const st = defaults();
  if (parts[0] === 'project' && parts[1]) { st.view = 'project'; st.slug = parts[1]; }
  else if (parts[0] === 'projects') st.view = 'projects';
  else if (VIEWS[parts[0]]) st.view = parts[0];
  for (const f of FIELDS) st.f[f] = p.get(f) ? p.get(f).split(',').filter(Boolean) : [];
  st.q = p.get('q') || '';
  st.layout = p.get('layout') === 'board' ? 'board' : 'list';
  st.group = GROUPS[p.get('group')] ? p.get('group') : 'status';
  st.order = ORDERS[p.get('order')] ? p.get('order') : 'priority';
  st.issue = p.get('issue') || null;
  st.open = p.get('open') || null;
  return st;
}

function defaults() {
  return { view: 'active', slug: null, f: Object.fromEntries(FIELDS.map(f => [f, []])), q: '', layout: 'list', group: 'status', order: 'priority', issue: null, open: null };
}

function hashOf(st) {
  const path = st.view === 'project' ? `/project/${encodeURIComponent(st.slug)}` : `/${st.view}`;
  const p = [];
  for (const f of FIELDS) if (st.f[f].length) p.push(`${f}=${st.f[f].map(encodeURIComponent).join(',')}`);
  if (st.q) p.push(`q=${encodeURIComponent(st.q)}`);
  if (st.layout !== 'list') p.push('layout=board');
  if (st.group !== 'status') p.push(`group=${st.group}`);
  if (st.order !== 'priority') p.push(`order=${st.order}`);
  if (st.issue) p.push(`issue=${encodeURIComponent(st.issue)}`);
  if (st.open) p.push(`open=${encodeURIComponent(st.open)}`);
  return '#' + path + (p.length ? '?' + p.join('&') : '');
}

function go(patch, { replace = false } = {}) {
  const next = { ...S, ...patch, f: patch.f ? patch.f : S.f };
  const viewChanged = next.view !== S.view || next.slug !== S.slug;
  if (viewChanged && !('issue' in patch)) next.issue = S.issue;
  const hash = hashOf(next);
  if (hash !== location.hash) history[replace ? 'replaceState' : 'pushState'](null, '', hash);
  apply(next);
}

function apply(next) {
  const prev = S;
  S = next;
  if (!D) return;
  const t = now();
  const listChanged = prev.view !== S.view || prev.slug !== S.slug || prev.q !== S.q || prev.layout !== S.layout ||
    prev.group !== S.group || prev.order !== S.order || FIELDS.some(f => prev.f?.[f]?.join() !== S.f[f].join()) || prev.__data !== D;
  if (listChanged) { renderNav(); renderHeader(); renderContent(); }
  if (prev.issue !== S.issue || prev.__data !== D) renderPeek();
  if (prev.open !== S.open) renderViewer();
  markRows();
  S.__data = D;
  document.title = S.issue && byId.get(S.issue) ? `${S.issue} ${byId.get(S.issue).title}` : `${viewName()} · ${D.name}`;
  timings.push({ what: listChanged ? 'view' : 'peek', ms: +(now() - t).toFixed(1) });
}

// ---------------------------------------------------------------- data

function setData(data) {
  D = data;
  byId = new Map(D.issues.map(i => [i.id, i]));
  projects = new Map(D.projects.map(p => [p.slug, p]));
  labelGroup = new Map();
  labelHue = new Map();
  for (const [group, labels] of Object.entries(D.labelGroups || {})) {
    labels.forEach((l, i) => { labelGroup.set(l, group); labelHue.set(l, Math.round((i * 360) / Math.max(labels.length, 1) + 18) % 360); });
  }
  for (const i of D.issues) {
    i._hay = `${i.id} ${i.num} ${i.title} ${i.kind} ${i.labels.join(' ')} ${i.projectName || ''}`.toLowerCase();
  }
  $('#hub-name').textContent = D.name;
  $('#hub-mark').textContent = (D.name || '?').slice(0, 1).toUpperCase();
}

async function refresh() {
  try {
    const res = await fetch('data/index.json', { cache: 'no-cache' });
    if (!res.ok) throw new Error(`index ${res.status}`);
    lastModified = res.headers.get('Last-Modified') || lastModified;
    if (lastModified) store.set(KEY + ':lm', lastModified);
    const text = await res.text();
    const data = JSON.parse(text);
    if (!D || data.version !== D.version) {
      pages.clear();
      setData(data);
      store.set(KEY, text);
      apply({ ...S });
    }
  } catch (err) {
    if (!D) $('#content').innerHTML = `<div class="empty"><strong>Can't load the issues</strong>${esc(err.message)}</div>`;
  }
  freshness();
}

function freshness() {
  const lm = lastModified || store.get(KEY + ':lm');
  if (!lm) return;
  const mins = Math.round((Date.now() - Date.parse(lm)) / 60000);
  $('#freshness').textContent = mins < 1 ? 'Updated just now' : mins < 60 ? `Updated ${mins} min ago` : mins < 1440 ? `Updated ${Math.round(mins / 60)} h ago` : `Updated ${fmtDate(Date.parse(lm) / 1000)}`;
  $('#freshness').title = new Date(lm).toLocaleString();
}

function page(url) {
  if (!pages.has(url)) {
    pages.set(url, fetch(url, { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); })
      .catch(err => { pages.delete(url); throw err; }));
  }
  return pages.get(url);
}
const issuePage = id => page(`data/issues/${encodeURIComponent(id)}.json`);
let prefetchTimer = 0;
function prefetch(id) {
  clearTimeout(prefetchTimer);
  prefetchTimer = setTimeout(() => { if (byId.has(id)) issuePage(id).catch(() => {}); }, 60);
}

// ---------------------------------------------------------------- filtering

function baseIssues(st = S) {
  if (st.view === 'project') return D.issues.filter(i => i.projectSlug === st.slug);
  const statuses = VIEWS[st.view]?.statuses;
  return statuses ? D.issues.filter(i => statuses.includes(i.status)) : D.issues;
}

function matches(i, f, skip) {
  if (skip !== 'status' && f.status.length && !f.status.includes(i.status)) return false;
  if (skip !== 'kind' && f.kind.length && !f.kind.includes(i.kind || 'None')) return false;
  if (skip !== 'priority' && f.priority.length && !f.priority.includes(String(i.priorityNum))) return false;
  if (skip !== 'project' && f.project.length && !f.project.includes(i.projectSlug || 'none')) return false;
  if (skip !== 'label' && f.label.length) {
    const byGroup = {};
    for (const l of f.label) (byGroup[labelGroup.get(l) || 'other'] ||= []).push(l);
    for (const want of Object.values(byGroup)) if (!want.some(l => i.labels.includes(l))) return false;
  }
  return true;
}

function textMatch(i, q) {
  if (!q) return true;
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  return words.every(w => i._hay.includes(w));
}

function visibleIssues() {
  return baseIssues().filter(i => matches(i, S.f) && textMatch(i, S.q));
}

function sorter(kind) {
  const by = {
    priority: (a, b) => PRI_RANK[a.priorityNum] - PRI_RANK[b.priorityNum] || b.updated - a.updated,
    updated: (a, b) => b.updated - a.updated,
    created: (a, b) => b.created - a.created || b.num - a.num,
    number: (a, b) => b.num - a.num,
  };
  return by[kind] || by.priority;
}

function grouped(list) {
  const sort = sorter(S.order);
  const groups = new Map();
  const keyOf = {
    status: i => i.status,
    project: i => i.projectSlug || '',
    kind: i => i.kind || '',
    priority: i => String(i.priorityNum),
    none: () => 'all',
  }[S.group];
  for (const i of list) {
    const k = keyOf(i);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(i);
  }
  let keys = [...groups.keys()];
  if (S.group === 'status') {
    const statuses = S.view === 'project' || S.view === 'all' ? STATUS_ORDER : VIEWS[S.view]?.statuses || STATUS_ORDER;
    keys = STATUS_ORDER.filter(s => statuses.includes(s) && (groups.has(s) || S.layout === 'board'));
  } else if (S.group === 'priority') keys.sort((a, b) => PRI_RANK[a] - PRI_RANK[b]);
  else if (S.group === 'kind') keys.sort((a, b) => (D.kinds.indexOf(a) + 1 || 99) - (D.kinds.indexOf(b) + 1 || 99));
  else if (S.group === 'project') keys.sort((a, b) => (!a) - (!b) || (projects.get(b)?.updated || 0) - (projects.get(a)?.updated || 0));
  return keys.map(k => ({ key: k, items: (groups.get(k) || []).sort(sort) }));
}

function groupTitle(key) {
  if (S.group === 'status') return `${stIcon(key)}<span>${esc(key)}</span>`;
  if (S.group === 'priority') return `${priIcon(+key)}<span>${esc(D.priorities[+key] || 'No priority')}</span>`;
  if (S.group === 'kind') return key ? kindTag(key) : '<span class="muted">No kind</span>';
  if (S.group === 'project') return key ? `${projIcon(projects.get(key)?.status)}<span>${esc(projects.get(key)?.name || key)}</span>` : '<span class="muted">No project</span>';
  return '<span>All issues</span>';
}

function viewName() {
  if (S.view === 'project') return projects.get(S.slug)?.name || S.slug;
  if (S.view === 'projects') return 'Projects';
  return VIEWS[S.view].name;
}

// ---------------------------------------------------------------- icons and tags

const ST_COLOR = { Backlog: 'var(--faint)', Todo: 'var(--muted)', 'In Progress': 'var(--amber)', 'In Review': 'var(--teal)', Done: 'var(--accent)', Canceled: 'var(--faint)' };
function stIcon(s) {
  const c = ST_COLOR[s] || 'var(--faint)';
  const ring = '<circle cx="7" cy="7" r="5.6"/>';
  const inner = {
    Backlog: '<circle cx="7" cy="7" r="5.6" stroke-dasharray="2.2 1.75"/>',
    Todo: ring,
    'In Progress': ring + '<path d="M7 3.6a3.4 3.4 0 0 1 0 6.8z" fill="currentColor" stroke="none"/>',
    'In Review': ring + '<path d="M7 7V3.6A3.4 3.4 0 1 1 3.6 7z" fill="currentColor" stroke="none"/>',
    Done: '<circle cx="7" cy="7" r="6.2" fill="currentColor" stroke="none"/><path d="m4.3 7.2 1.9 1.9 3.5-3.7" stroke="var(--surface)" stroke-width="1.6"/>',
    Canceled: '<circle cx="7" cy="7" r="6.2" fill="currentColor" stroke="none"/><path d="m4.9 4.9 4.2 4.2M9.1 4.9 4.9 9.1" stroke="var(--surface)" stroke-width="1.5"/>',
  }[s] || ring;
  return `<svg class="st" viewBox="0 0 14 14" style="color:${c}" aria-label="${esc(s)}">${inner}</svg>`;
}
function projIcon(s) {
  const map = { Backlog: 'Backlog', Planned: 'Todo', 'In Progress': 'In Progress', 'In Review': 'In Review', Completed: 'Done', Done: 'Done', Canceled: 'Canceled', Paused: 'Backlog' };
  return stIcon(map[s] || 'Todo');
}
function priIcon(n) {
  if (n === 1) return '<svg class="pri urgent" viewBox="0 0 14 14" aria-label="Urgent"><rect x="1" y="1" width="12" height="12" rx="3"/><path d="M7 3.9v3.8" stroke="var(--surface)" stroke-width="1.7"/><circle cx="7" cy="10.1" r=".95" fill="var(--surface)" stroke="none"/></svg>';
  if (!n) return '<svg class="pri" viewBox="0 0 14 14" aria-label="No priority"><rect x="1.5" y="6.4" width="2.6" height="1.3" rx=".6" class="off"/><rect x="5.7" y="6.4" width="2.6" height="1.3" rx=".6" class="off"/><rect x="9.9" y="6.4" width="2.6" height="1.3" rx=".6" class="off"/></svg>';
  const lit = { 2: 3, 3: 2, 4: 1 }[n] || 0;
  const bars = [[1.5, 8, 4], [5.7, 5, 7], [9.9, 2, 10]].map(([x, y, h], k) => `<rect x="${x}" y="${y}" width="2.6" height="${h}" rx=".8"${k < lit ? '' : ' class="off"'}/>`).join('');
  return `<svg class="pri" viewBox="0 0 14 14" aria-label="${esc(D?.priorities[n] || '')}">${bars}</svg>`;
}
const folderIcon = '<svg viewBox="0 0 16 16"><path d="M2.5 4.5h4l1.5 1.5h5.5v6.5h-11z"/></svg>';
function kindTag(k) {
  return k ? `<span class="tag kind" style="--c:hsl(${KIND_HUES[k] ?? 260} 58% 52%)"><i></i>${esc(k)}</span>` : '';
}
function labelTag(l) {
  const group = labelGroup.get(l);
  if (group === 'platform') return `<span class="tag plat">${esc(l)}</span>`;
  const hue = labelHue.get(l) ?? hashHue(l);
  return `<span class="tag" style="--c:hsl(${hue} 50% ${group ? 52 : 60}%)"><i></i>${esc(l)}</span>`;
}
function hashHue(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
function fmtDate(sec) {
  if (!sec) return '';
  const d = new Date(sec * 1000);
  const same = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(undefined, same ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' });
}
function fullDate(sec) { return sec ? new Date(sec * 1000).toLocaleString() : ''; }

// ---------------------------------------------------------------- sidebar and header

function counts(list) {
  const c = {};
  for (const i of list) c[i.status] = (c[i.status] || 0) + 1;
  return c;
}

function renderNav() {
  const c = counts(D.issues);
  const n = statuses => statuses ? statuses.reduce((a, s) => a + (c[s] || 0), 0) : D.issues.length;
  const item = (href, label, count, on, extra = '') => `<a class="nav-item${on ? ' on' : ''}" href="${href}">${extra}<span class="label-text">${esc(label)}</span>${count !== '' ? `<span class="n">${count}</span>` : ''}</a>`;
  const openIssues = D.issues.filter(i => D.openStatuses.includes(i.status));
  let html = '';
  html += item('#/active', 'Active', n(VIEWS.active.statuses), S.view === 'active', stIcon('In Progress'));
  html += item('#/backlog', 'Backlog', n(VIEWS.backlog.statuses), S.view === 'backlog', stIcon('Backlog'));
  html += item('#/all', 'All issues', D.issues.length, S.view === 'all', '<svg viewBox="0 0 16 16"><path d="M3 4.5h10M3 8h10M3 11.5h10"/></svg>');
  html += item('#/done', 'Done', n(VIEWS.done.statuses), S.view === 'done', stIcon('Done'));
  html += item('#/projects', 'Projects', D.projects.filter(p => !p.orphan).length, S.view === 'projects', folderIcon);
  if (D.pages?.length) {
    html += '<div class="nav-label">Hub</div>';
    for (const key of D.pages) html += `<button class="nav-item" data-open="page:${esc(key)}"><svg viewBox="0 0 16 16"><path d="M4 2.5h5.5l2.5 2.5v8.5h-8z"/><path d="M9.5 2.5V5H12"/></svg><span class="label-text">${esc(key === 'ROADMAP.md' ? 'Roadmap' : key === 'HUB.md' ? 'House rules' : key)}</span></button>`;
  }
  const kindCount = {};
  for (const i of openIssues) if (i.kind) kindCount[i.kind] = (kindCount[i.kind] || 0) + 1;
  html += '<div class="nav-label">Kinds <span>open</span></div>';
  for (const k of D.kinds) {
    const on = S.f.kind.length === 1 && S.f.kind[0] === k;
    html += `<button class="nav-item${on ? ' on' : ''}" data-filter="kind" data-value="${esc(k)}"><span class="dot" style="background:hsl(${KIND_HUES[k] ?? 260} 58% 52%);border-radius:2px"></span><span class="label-text">${esc(k)}</span><span class="n">${kindCount[k] || 0}</span></button>`;
  }
  const areas = D.labelGroups?.area || [];
  if (areas.length) {
    const areaCount = {};
    for (const i of openIssues) for (const l of i.labels) areaCount[l] = (areaCount[l] || 0) + 1;
    html += '<div class="nav-label">Areas <span>open</span></div>';
    for (const a of areas) {
      const on = S.f.label.length === 1 && S.f.label[0] === a;
      html += `<button class="nav-item${on ? ' on' : ''}" data-filter="label" data-value="${esc(a)}"><span class="dot" style="background:hsl(${labelHue.get(a)} 50% 52%)"></span><span class="label-text">${esc(a)}</span><span class="n">${areaCount[a] || 0}</span></button>`;
    }
  }
  const live = D.projects.filter(p => !p.orphan && !PROJECT_DONE.includes(p.status)).slice(0, 12);
  if (live.length) {
    html += '<div class="nav-label">Projects</div>';
    for (const p of live) html += item(`#/project/${encodeURIComponent(p.slug)}`, p.name, '', S.view === 'project' && S.slug === p.slug, projIcon(p.status));
  }
  $('#nav').innerHTML = html;
}

function renderHeader() {
  $('#view-title').textContent = viewName();
  const projectsView = S.view === 'projects';
  $('#filterbar').hidden = projectsView;
  $('.seg').hidden = projectsView;
  $('#display-btn').hidden = projectsView;
  $('#layout-list').classList.toggle('on', S.layout === 'list');
  $('#layout-board').classList.toggle('on', S.layout === 'board');
  const search = $('#search');
  if (document.activeElement !== search) search.value = S.q;
  search.placeholder = projectsView ? 'Filter projects' : 'Filter by text';
  renderChips();
  renderProjectHead();
}

function chipGroups() {
  const out = [];
  if (S.f.status.length) out.push({ field: 'status', key: 'Status', values: S.f.status, html: v => `${stIcon(v)}${esc(v)}` });
  if (S.f.priority.length) out.push({ field: 'priority', key: 'Priority', values: S.f.priority, html: v => `${priIcon(+v)}${esc(D.priorities[+v])}` });
  if (S.f.kind.length) out.push({ field: 'kind', key: 'Kind', values: S.f.kind, html: v => esc(v) });
  const byGroup = {};
  for (const l of S.f.label) (byGroup[labelGroup.get(l) || 'other'] ||= []).push(l);
  for (const [g, values] of Object.entries(byGroup)) out.push({ field: 'label', key: g === 'other' ? 'Label' : g[0].toUpperCase() + g.slice(1), values, html: v => esc(v) });
  if (S.f.project.length) out.push({ field: 'project', key: 'Project', values: S.f.project, html: v => esc(v === 'none' ? 'No project' : projects.get(v)?.name || v) });
  return out;
}

function renderChips() {
  const xIcon = '<svg viewBox="0 0 16 16"><path d="m4.5 4.5 7 7M11.5 4.5l-7 7"/></svg>';
  $('#chips').innerHTML = chipGroups().map((c, n) => {
    const shown = c.values.length > 2 ? `${c.values.length} values` : c.values.map(c.html).join('<span class="muted">,</span> ');
    return `<span class="chip"><span class="k">${esc(c.key)}</span><span class="op">${c.values.length > 1 ? 'is any of' : 'is'}</span><span>${shown}</span><button data-chip="${n}" aria-label="Remove filter">${xIcon}</button></span>`;
  }).join('');
  $('#filter-btn').lastChild.textContent = chipGroups().length ? '' : 'Filter';
}

function progressBar(p) {
  const total = (p.total || 0) - (p.counts?.Canceled || 0);
  const done = p.counts?.Done || 0;
  const ip = (p.counts?.['In Progress'] || 0) + (p.counts?.['In Review'] || 0);
  const pct = total ? Math.round((done / total) * 100) : 0;
  return { pct, done, total, html: `<span class="bar"><b style="width:${total ? (done / total) * 100 : 0}%"></b><b class="ip" style="width:${total ? (ip / total) * 100 : 0}%"></b></span>` };
}

function docChip(d, opts = {}) {
  if (d.type === 'artifact' && d.dead) return `<span class="doc dead" title="This published page is gone"><span class="ext art">ART</span><span class="nm">${esc(d.name === 'artifact' ? 'Published page' : d.name)} · gone</span></span>`;
  if (d.type === 'artifact') return `<a class="doc" href="${esc(d.href)}" target="_blank" rel="noreferrer"><span class="ext art">ART</span><span class="nm">${esc(d.name === 'artifact' ? 'Published page' : d.name)}</span></a>`;
  if (d.type === 'project') return `<a class="doc" href="#/project/${encodeURIComponent(d.slug)}">${folderIcon}<span class="nm">${esc(d.name || d.slug)}</span></a>`;
  if (d.type === 'doc') return `<button class="doc" data-open="doc:${esc(d.slug)}"><span class="ext md">DOC</span><span class="nm">${esc(d.name || d.slug)}</span></button>`;
  if (d.type === 'page') return `<button class="doc" data-open="page:${esc(d.key)}"><span class="ext md">MD</span><span class="nm">${esc(d.name)}</span></button>`;
  const ext = (d.ext || '').toLowerCase();
  const plan = opts.plan && d.path === opts.plan;
  const label = plan ? 'Illustrated plan' : d.name;
  if (d.download) return `<a class="doc" href="hub/${esc(d.path)}" target="_blank" rel="noreferrer"><span class="ext">${esc(ext.slice(0, 4))}</span><span class="nm">${esc(label)}</span></a>`;
  return `<button class="doc${plan ? ' plan' : ''}" data-open="file:${esc(d.path)}"><span class="ext ${esc(ext)}">${esc(ext.slice(0, 4))}</span><span class="nm">${esc(label)}</span></button>`;
}

function renderProjectHead() {
  const head = $('#project-head');
  const p = S.view === 'project' && projects.get(S.slug);
  if (!p) { head.hidden = true; head.innerHTML = ''; return; }
  const bar = progressBar(p);
  const meta = [];
  if (p.status) meta.push(`<span class="pstatus">${projIcon(p.status)}<b>${esc(p.status)}</b></span>`);
  meta.push(`<span class="progress">${bar.html}${bar.pct}% · ${bar.done}/${bar.total} done</span>`);
  if (p.release) meta.push(`<span>Release <b>${esc(p.release)}</b></span>`);
  if (p.lead) meta.push(`<span>Lead <b>${esc(p.lead)}</b></span>`);
  if (p.target && p.target !== 'N/A') meta.push(`<span>Target <b>${esc(p.target)}</b></span>`);
  if (p.start) meta.push(`<span>Started <b>${esc(p.start)}</b></span>`);
  const plan = p.plan ? `<button class="btn primary" data-open="file:${esc(p.plan)}">Open plan <kbd>p</kbd></button>` : '';
  head.hidden = false;
  head.innerHTML = `<div class="ph-top">${folderIcon}<h2>${esc(p.name)}</h2>${plan}</div>
    <div class="ph-meta">${meta.join('')}</div>
    ${p.summary ? `<p class="ph-summary">${esc(p.summary)}</p>` : ''}
    ${p.documents?.length ? `<div class="ph-docs">${p.documents.map(d => docChip(d, { plan: p.plan })).join('')}</div>` : ''}
    ${p.orphan ? '' : `<details class="ph-overview" id="ph-overview"><summary>Project overview</summary><div class="prose" id="ph-overview-body">Loading…</div></details>`}`;
  const details = $('#ph-overview');
  details?.addEventListener('toggle', () => {
    if (!details.open) return;
    page(`data/projects/${encodeURIComponent(p.slug)}.json`).then(pg => fillProse($('#ph-overview-body'), pg.html)).catch(() => { $('#ph-overview-body').textContent = 'Could not load the project page.'; });
  }, { once: true });
}

// ---------------------------------------------------------------- content

const commentIcon = '<svg viewBox="0 0 16 16"><path d="M3 3.5h10v7H7l-3 2.5v-2.5H3z"/></svg>';

function rowHtml(i) {
  const tags = [kindTag(i.kind), ...i.labels.slice(0, 3).map(labelTag)];
  if (i.labels.length > 3) tags.push(`<span class="tag">+${i.labels.length - 3}</span>`);
  if (i.projectSlug && S.view !== 'project') tags.push(`<span class="tag project">${folderIcon}${esc(i.projectName || i.projectSlug)}</span>`);
  return `<div class="row" data-id="${i.id}">${priIcon(i.priorityNum)}<span class="id">${i.id}</span>${stIcon(i.status)}<span class="title">${esc(i.title)}</span><span class="tags">${tags.join('')}</span><span class="comments">${i.commentCount ? commentIcon + i.commentCount : ''}</span><span class="date" title="Updated ${esc(fullDate(i.updated))}">${fmtDate(i.updated)}</span></div>`;
}

function cardHtml(i) {
  const tags = [kindTag(i.kind), ...i.labels.slice(0, 3).map(labelTag)].join('');
  return `<div class="card" data-id="${i.id}"><div class="card-top">${stIcon(i.status)}<span>${i.id}</span>${priIcon(i.priorityNum)}</div><div class="card-title">${esc(i.title)}</div>${tags ? `<div class="card-tags">${tags}</div>` : ''}</div>`;
}

function renderContent() {
  const content = $('#content');
  if (S.view === 'projects') return renderProjects();
  const list = visibleIssues();
  $('#view-count').textContent = list.length;
  const groups = grouped(list);
  order = [];
  if (!list.length) {
    content.innerHTML = `<div class="empty"><strong>No issues match</strong>${S.q || chipGroups().length ? 'Try removing a filter or the search text. <kbd>x</kbd> clears filters.' : ''}</div>`;
    return;
  }
  const limit = S.layout === 'board' ? 60 : 250;
  let html = '';
  if (S.layout === 'board') {
    html = '<div class="board">' + groups.map(g => {
      const key = `${S.view}:${g.key}`;
      const shown = expanded.has(key) ? g.items : g.items.slice(0, limit);
      shown.forEach(i => order.push(i.id));
      return `<section class="col"><div class="col-head">${groupTitle(g.key)}<span class="n">${g.items.length}</span></div><div class="col-cards">${shown.map(cardHtml).join('')}${g.items.length > shown.length ? `<button class="more" data-more="${esc(key)}">Show ${g.items.length - shown.length} more</button>` : ''}</div></section>`;
    }).join('') + '</div>';
  } else {
    html = groups.map(g => {
      const key = `${S.view}:${g.key}`;
      const isClosed = closed.has(`${S.view}:${S.group}:${g.key}`);
      const shown = expanded.has(key) ? g.items : g.items.slice(0, limit);
      if (!isClosed) shown.forEach(i => order.push(i.id));
      return `<section class="group${isClosed ? ' closed' : ''}"><button class="group-head" data-group="${esc(g.key)}"><svg class="chev" viewBox="0 0 12 12"><path d="m3 4.5 3 3 3-3"/></svg>${groupTitle(g.key)}<span class="n">${g.items.length}</span></button><div class="rows">${shown.map(rowHtml).join('')}${g.items.length > shown.length ? `<button class="more" data-more="${esc(key)}">Show ${g.items.length - shown.length} more</button>` : ''}</div></section>`;
    }).join('');
  }
  content.innerHTML = html;
  if (!order.includes(sel)) sel = null;
}

function projectList() {
  const q = S.q.toLowerCase();
  return D.projects.filter(p => !p.orphan && (!q || p.name.toLowerCase().includes(q) || (p.status || '').toLowerCase().includes(q)))
    .sort((a, b) => PROJECT_DONE.includes(a.status) - PROJECT_DONE.includes(b.status) || b.updated - a.updated);
}

function renderProjects() {
  const list = projectList();
  $('#view-count').textContent = list.length;
  order = list.map(p => 'project:' + p.slug);
  if (!order.includes(sel)) sel = null;
  $('#content').innerHTML = `<table class="ptable"><thead><tr><th>Name</th><th>Status</th><th>Progress</th><th class="hide-sm">Release</th><th class="hide-sm">Docs</th><th class="hide-sm">Updated</th></tr></thead><tbody>${list.map(p => {
    const bar = progressBar(p);
    const open = (p.total || 0) - (p.counts?.Done || 0) - (p.counts?.Canceled || 0);
    return `<tr class="prow" data-id="project:${esc(p.slug)}"><td><span class="pname">${projIcon(p.status)}${esc(p.name)}</span></td><td class="muted">${esc(p.status)}</td><td><span class="progress">${bar.html}${bar.pct}%<span class="muted">${open ? ` · ${open} open` : ''}</span></span></td><td class="muted hide-sm">${esc(p.release || '')}</td><td class="muted hide-sm">${p.plan ? 'Plan' : ''}${p.documents.length > (p.plan ? 1 : 0) ? `${p.plan ? ' + ' : ''}${p.documents.length - (p.plan ? 1 : 0)}` : ''}</td><td class="muted hide-sm">${fmtDate(p.updated)}</td></tr>`;
  }).join('')}</tbody></table>`;
}

function markRows() {
  const content = $('#content');
  content.querySelectorAll('.sel,.open').forEach(el => el.classList.remove('sel', 'open'));
  if (S.issue) content.querySelector(`[data-id="${CSS.escape(S.issue)}"]`)?.classList.add('open');
  if (sel) content.querySelector(`[data-id="${CSS.escape(sel)}"]`)?.classList.add('sel');
}

function move(step) {
  if (!order.length) return;
  let at = order.indexOf(sel ?? S.issue);
  at = at < 0 ? (step > 0 ? 0 : order.length - 1) : Math.min(order.length - 1, Math.max(0, at + step));
  sel = order[at];
  markRows();
  const el = $('#content').querySelector(`[data-id="${CSS.escape(sel)}"]`);
  el?.scrollIntoView({ block: 'nearest' });
  if (!sel.startsWith('project:')) {
    prefetch(sel);
    if (S.issue) go({ issue: sel }, { replace: true });
  }
}

function openSelected() {
  if (!sel) return;
  if (sel.startsWith('project:')) go({ view: 'project', slug: sel.slice(8), f: defaults().f, q: '' });
  else go({ issue: sel }, { replace: !!S.issue });
}

// ---------------------------------------------------------------- peek

let peekToken = 0;
function renderPeek() {
  const peek = $('#peek');
  const i = S.issue && byId.get(S.issue);
  if (!i) { peek.hidden = true; peek.innerHTML = ''; return; }
  const token = ++peekToken;
  const p = i.projectSlug && projects.get(i.projectSlug);
  const props = [
    ['Status', `<button class="v" data-filter="status" data-value="${esc(i.status)}">${stIcon(i.status)}${esc(i.status)}</button>`],
    ['Priority', `<button class="v" data-filter="priority" data-value="${i.priorityNum}">${priIcon(i.priorityNum)}${esc(D.priorities[i.priorityNum] || 'No priority')}</button>`],
    ['Kind', i.kind ? `<button class="v" data-filter="kind" data-value="${esc(i.kind)}">${kindTag(i.kind)}</button>` : '<span class="muted">None</span>'],
    ['Labels', i.labels.length ? i.labels.map(l => `<button class="v" data-filter="label" data-value="${esc(l)}">${labelTag(l)}</button>`).join('') : '<span class="muted">None</span>'],
    ['Project', p ? `<a class="tag project" href="#/project/${encodeURIComponent(p.slug)}">${folderIcon}${esc(p.name)}</a>` : i.projectName ? esc(i.projectName) : '<span class="muted">None</span>'],
    ['Created', `<span title="${esc(fullDate(i.created))}">${fmtDate(i.created)}</span>`],
    ['Updated', `<span title="${esc(fullDate(i.updated))}">${fmtDate(i.updated)}</span>`],
  ];
  let projectCard = '';
  if (p) {
    const bar = progressBar(p);
    const siblings = D.issues.filter(x => x.projectSlug === p.slug && x.id !== i.id && D.openStatuses.includes(x.status)).sort(sorter('priority')).slice(0, 6);
    projectCard = `<div class="section"><h3>Project</h3><div class="pcard">
      <div class="pcard-top">${projIcon(p.status)}<a href="#/project/${encodeURIComponent(p.slug)}">${esc(p.name)}</a><span class="muted" style="margin-left:auto;font-size:12px">${esc(p.status || '')}</span></div>
      ${bar.html}
      <div class="pcard-meta"><span>${bar.pct}% · ${bar.done}/${bar.total} done</span>${p.release ? `<span>${esc(p.release)}</span>` : ''}${p.target && p.target !== 'N/A' ? `<span>Target ${esc(p.target)}</span>` : ''}</div>
      ${p.summary ? `<p>${esc(p.summary)}</p>` : ''}
      ${p.documents?.length ? `<div class="docs">${p.documents.map(d => docChip(d, { plan: p.plan })).join('')}</div>` : ''}
      ${siblings.length ? `<div>${siblings.map(x => relRow(x.id, '')).join('')}</div>` : ''}
    </div></div>`;
  }
  peek.hidden = false;
  peek.innerHTML = `<div class="peek-bar"><span class="id">${i.id}</span><span class="grow"></span>
      <button class="icon-btn" data-act="copy" title="Copy link (c)" aria-label="Copy link"><svg viewBox="0 0 16 16"><path d="M6.5 9.5l3-3M7 4.8l1-1a2.6 2.6 0 0 1 3.7 3.7l-1 1M9 11.2l-1 1a2.6 2.6 0 0 1-3.7-3.7l1-1"/></svg></button>
      <button class="icon-btn" data-act="prev" title="Previous (k)" aria-label="Previous"><svg viewBox="0 0 16 16"><path d="m4.5 10 3.5-3.5 3.5 3.5"/></svg></button>
      <button class="icon-btn" data-act="next" title="Next (j)" aria-label="Next"><svg viewBox="0 0 16 16"><path d="m4.5 6 3.5 3.5 3.5-3.5"/></svg></button>
      <button class="icon-btn" data-act="close" title="Close (esc)" aria-label="Close"><svg viewBox="0 0 16 16"><path d="m4 4 8 8M12 4l-8 8"/></svg></button></div>
    <div class="peek-body"><h2>${esc(i.title)}</h2>
      <dl class="props">${props.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>
      ${projectCard}
      <div id="peek-extra"></div>
      <div class="prose" id="peek-prose"><p class="muted">Loading…</p></div>
      <div class="file-path" id="peek-file"></div>
    </div>`;
  peek.querySelector('.peek-body').scrollTop = 0;
  issuePage(i.id).then(pg => {
    if (token !== peekToken) return;
    const rels = pg.relations || [];
    const files = (pg.attachments || []).filter(a => a.type !== 'project');
    const images = files.filter(a => a.type === 'file' && /^(png|jpe?g|gif|webp|svg)$/.test(a.ext));
    const others = files.filter(a => !images.includes(a));
    let extra = '';
    if (rels.length) {
      const order = ['Blocked by', 'Blocks', 'Follows', 'Followed by', 'Related', 'Duplicate of', 'Duplicated by'];
      rels.sort((a, b) => (order.indexOf(a.rel) + 1 || 99) - (order.indexOf(b.rel) + 1 || 99));
      extra += `<div class="section"><h3>Related issues</h3>${rels.map(r => relRow(r.id, r.rel)).join('')}</div>`;
    }
    if (files.length) {
      extra += `<div class="section"><h3>Files and pages <span>${files.length}</span></h3>`;
      if (others.length) extra += `<div class="docs">${others.slice(0, 8).map(d => docChip(d)).join('')}</div>`;
      if (others.length > 8) extra += `<details class="more-files"><summary>Show ${others.length - 8} more</summary><div class="docs">${others.slice(8).map(d => docChip(d)).join('')}</div></details>`;
      if (images.length) extra += `<div class="thumbs">${images.slice(0, 24).map(a => `<button class="thumb" data-open="file:${esc(a.path)}" title="${esc(a.name)}"><img loading="lazy" src="hub/${esc(a.path)}" alt="${esc(a.name)}"></button>`).join('')}</div>`;
      extra += '</div>';
    }
    $('#peek-extra').innerHTML = extra;
    fillProse($('#peek-prose'), pg.html || '<p class="muted">No description.</p>');
    $('#peek-file').textContent = pg.file || '';
  }).catch(() => { if (token === peekToken) $('#peek-prose').innerHTML = '<p class="muted">Could not load this issue.</p>'; });
}

function relRow(id, rel) {
  const x = byId.get(id);
  if (!x) return `<div class="rel"><span class="id">${esc(id)}</span><span class="t muted">Not in this hub</span><span class="r">${esc(rel)}</span></div>`;
  return `<button class="rel" data-issue="${x.id}">${stIcon(x.status)}<span class="id">${x.id}</span><span class="t">${esc(x.title)}</span>${rel ? `<span class="r">${esc(rel)}</span>` : priIcon(x.priorityNum)}</button>`;
}

function fillProse(el, html) {
  el.innerHTML = html;
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
    acceptNode: n => n.parentElement.closest('a,code,pre') || !ID_RE.test(n.data) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    ID_RE.lastIndex = 0;
    const frag = document.createDocumentFragment();
    let last = 0;
    for (const m of node.data.matchAll(ID_RE)) {
      if (!byId.has(m[1])) continue;
      frag.append(node.data.slice(last, m.index));
      const a = document.createElement('a');
      a.href = '#' + m[1];
      a.className = 'idlink';
      a.textContent = m[1];
      a.title = byId.get(m[1]).title;
      frag.append(a);
      last = m.index + m[0].length;
    }
    if (last) { frag.append(node.data.slice(last)); node.replaceWith(frag); }
  }
  ID_RE.lastIndex = 0;
}

// ---------------------------------------------------------------- document viewer

function openTarget(target) { go({ open: target }, { replace: !!S.open }); }

function renderViewer() {
  const layer = $('#viewer');
  if (!S.open) { layer.hidden = true; $('#viewer-body').innerHTML = ''; return; }
  const [type, ...rest] = S.open.split(':');
  const ref = rest.join(':');
  const body = $('#viewer-body');
  const tab = $('#viewer-tab');
  layer.hidden = false;
  body.innerHTML = '';
  if (type === 'file') {
    const src = 'hub/' + ref.split('/').map(encodeURIComponent).join('/');
    const plan = D.projects.find(p => p.plan === ref);
    $('#viewer-title').textContent = plan ? `${plan.name} · illustrated plan` : ref;
    tab.href = src;
    tab.hidden = false;
    const ext = ref.split('.').pop().toLowerCase();
    if (/^(png|jpe?g|gif|webp|svg)$/.test(ext)) body.innerHTML = `<div class="img-wrap"><img src="${esc(src)}" alt="${esc(ref)}"></div>`;
    else if (/^(mp4|mov|webm)$/.test(ext)) body.innerHTML = `<div class="img-wrap"><video src="${esc(src)}" controls autoplay style="max-width:100%;max-height:85vh"></video></div>`;
    else {
      body.innerHTML = `<iframe src="${esc(src)}" title="${esc(ref)}"></iframe>`;
      const frame = body.firstElementChild;
      frame.addEventListener('load', () => {
        try { frame.contentWindow.addEventListener('keydown', e => { if (e.key === 'Escape') closeTop(); }); } catch {}
      });
    }
    return;
  }
  const url = type === 'doc' ? `data/docs/${encodeURIComponent(ref)}.json` : `data/pages/${encodeURIComponent(ref.replaceAll('/', '~'))}.json`;
  $('#viewer-title').textContent = ref;
  tab.href = type === 'doc' ? `hub/documents/${encodeURIComponent(ref)}.md` : `hub/${ref}`;
  tab.hidden = true;
  body.innerHTML = '<div class="prose"><p class="muted">Loading…</p></div>';
  const current = S.open;
  page(url).then(pg => {
    if (S.open !== current) return;
    $('#viewer-title').textContent = pg.name || ref;
    fillProse(body.firstElementChild, pg.html);
  }).catch(() => {
    if (S.open !== current) return;
    tab.hidden = false;
    body.innerHTML = '<div class="prose"><p class="muted">This page isn\'t in the export. Open the raw file instead.</p></div>';
  });
}

// ---------------------------------------------------------------- command palette

let paletteItems = [];
let paletteAt = 0;

function openPalette() {
  closePopover();
  $('#palette').hidden = false;
  const input = $('#palette-input');
  input.value = '';
  renderPalette();
  input.focus();
}
function closePalette() { $('#palette').hidden = true; }

function mark(text, q) {
  if (!q) return esc(text);
  const at = text.toLowerCase().indexOf(q.toLowerCase());
  return at < 0 ? esc(text) : esc(text.slice(0, at)) + '<mark>' + esc(text.slice(at, at + q.length)) + '</mark>' + esc(text.slice(at + q.length));
}

function commands() {
  const cmds = [
    { t: 'Go to Active', hint: 'g a', run: () => goView('active') },
    { t: 'Go to Backlog', hint: 'g b', run: () => goView('backlog') },
    { t: 'Go to All issues', hint: 'g l', run: () => goView('all') },
    { t: 'Go to Done', hint: 'g d', run: () => goView('done') },
    { t: 'Go to Projects', hint: 'g p', run: () => goView('projects') },
    { t: S.layout === 'board' ? 'Show as list' : 'Show as board', hint: 'b', run: () => go({ layout: S.layout === 'board' ? 'list' : 'board' }) },
    { t: 'Add a filter', hint: 'f', run: () => openFilter() },
    { t: 'Clear filters', hint: 'x', run: () => clearFilters() },
    { t: 'Switch theme', hint: '', run: () => toggleTheme() },
    { t: 'Keyboard shortcuts', hint: '?', run: () => { $('#help').hidden = false; } },
  ];
  for (const key of D.pages || []) cmds.push({ t: key === 'ROADMAP.md' ? 'Open the roadmap' : key === 'HUB.md' ? 'Open the house rules' : `Open ${key}`, hint: '', run: () => openTarget('page:' + key) });
  for (const g of Object.keys(GROUPS)) cmds.push({ t: `Group by ${GROUPS[g].toLowerCase()}`, hint: '', run: () => go({ group: g }) });
  for (const h of HUBS) if (h.slug !== HUB_SLUG) cmds.push({ t: `Switch to ${h.name}`, hint: h.prefix ? `${h.prefix}-` : '', run: () => switchHub(h.slug) });
  if (HUBS.length > 1) cmds.push({ t: 'Show all hubs', hint: 'g h', run: () => openHubs() });
  return cmds;
}

function renderPalette() {
  const q = $('#palette-input').value.trim();
  const ql = q.toLowerCase();
  const items = [];
  const num = q.match(/^(?:[a-z][a-z0-9]*-)?(\d+)$/i);
  if (num) {
    const hit = D.issues.find(i => i.num === +num[1]);
    if (hit) items.push({ section: 'Issues', kind: 'issue', i: hit });
  }
  const cmds = commands().filter(c => !ql || c.t.toLowerCase().includes(ql)).slice(0, ql ? 5 : 6);
  cmds.forEach(c => items.push({ section: 'Commands', kind: 'cmd', c }));
  const projs = D.projects.filter(p => !p.orphan && ql && p.name.toLowerCase().includes(ql)).slice(0, 5);
  projs.forEach(p => items.push({ section: 'Projects', kind: 'project', p }));
  let issues;
  if (!ql) issues = [...D.issues].sort((a, b) => b.updated - a.updated).slice(0, 8);
  else {
    const words = ql.split(/\s+/);
    issues = D.issues.filter(i => words.every(w => i._hay.includes(w)) && !(num && i.num === +num[1]))
      .map(i => ({ i, s: (i.title.toLowerCase().startsWith(ql) ? 0 : i.title.toLowerCase().includes(ql) ? 1 : 2) + (D.openStatuses.includes(i.status) ? 0 : 0.5) }))
      .sort((a, b) => a.s - b.s || b.i.updated - a.i.updated).slice(0, 40).map(x => x.i);
  }
  issues.forEach(i => items.push({ section: ql ? 'Issues' : 'Recently updated', kind: 'issue', i }));
  paletteItems = items;
  paletteAt = 0;
  let html = '';
  let section = '';
  items.forEach((it, n) => {
    if (it.section !== section) { section = it.section; html += `<div class="p-head">${esc(section)}</div>`; }
    if (it.kind === 'issue') html += `<div class="p-item" data-n="${n}" role="option">${stIcon(it.i.status)}<span class="id">${it.i.id}</span><span class="t">${mark(it.i.title, q)}</span>${it.i.projectName ? `<span class="hint">${esc(it.i.projectName)}</span>` : ''}</div>`;
    else if (it.kind === 'project') html += `<div class="p-item" data-n="${n}" role="option">${projIcon(it.p.status)}<span class="t">${mark(it.p.name, q)}</span><span class="hint">Project</span></div>`;
    else html += `<div class="p-item" data-n="${n}" role="option"><svg viewBox="0 0 16 16"><path d="m6 4 4 4-4 4"/></svg><span class="t">${mark(it.c.t, q)}</span>${it.c.hint ? `<span class="hint"><kbd>${esc(it.c.hint)}</kbd></span>` : ''}</div>`;
  });
  $('#palette-list').innerHTML = html || '<div class="empty">Nothing matches.</div>';
  highlightPalette();
}

function highlightPalette() {
  const list = $('#palette-list');
  list.querySelectorAll('.p-item.on').forEach(el => el.classList.remove('on'));
  const el = list.querySelector(`[data-n="${paletteAt}"]`);
  el?.classList.add('on');
  el?.scrollIntoView({ block: 'nearest' });
  const it = paletteItems[paletteAt];
  if (it?.kind === 'issue') prefetch(it.i.id);
}

function runPalette(n) {
  const it = paletteItems[n];
  if (!it) return;
  closePalette();
  if (it.kind === 'issue') { sel = it.i.id; go({ issue: it.i.id }); }
  else if (it.kind === 'project') go({ view: 'project', slug: it.p.slug, f: defaults().f, q: '' });
  else it.c.run();
}

// ---------------------------------------------------------------- filter and display popovers

let popItems = [];
let popAt = 0;

function closePopover() { $('#popover').hidden = true; $('#popover').innerHTML = ''; }

function place(pop, anchor) {
  const r = anchor.getBoundingClientRect();
  pop.style.top = `${Math.min(r.bottom + 6, innerHeight - 200)}px`;
  pop.style.left = `${Math.max(8, Math.min(r.left, innerWidth - 290))}px`;
}

function filterOptions() {
  const base = baseIssues();
  const opts = [];
  const count = (field, value) => base.filter(i => matches(i, S.f, field) && ({
    status: i.status === value, priority: String(i.priorityNum) === value, kind: (i.kind || 'None') === value,
    label: i.labels.includes(value), project: (i.projectSlug || 'none') === value,
  })[field]).length;
  const statuses = S.view === 'project' || S.view === 'all' ? STATUS_ORDER : VIEWS[S.view].statuses;
  for (const s of statuses) opts.push({ field: 'status', group: 'Status', value: s, label: s, icon: stIcon(s) });
  for (const n of [1, 2, 3, 4, 0]) opts.push({ field: 'priority', group: 'Priority', value: String(n), label: D.priorities[n], icon: priIcon(n) });
  for (const k of D.kinds) opts.push({ field: 'kind', group: 'Kind', value: k, label: k, icon: `<span class="dot" style="width:8px;height:8px;border-radius:2px;background:hsl(${KIND_HUES[k] ?? 260} 58% 52%)"></span>` });
  for (const [g, labels] of Object.entries(D.labelGroups || {})) for (const l of labels) opts.push({ field: 'label', group: g[0].toUpperCase() + g.slice(1), value: l, label: l });
  const grouped = new Set(labelGroup.keys());
  const others = [...new Set(base.flatMap(i => i.labels))].filter(l => !grouped.has(l)).sort();
  for (const l of others) opts.push({ field: 'label', group: 'Label', value: l, label: l });
  if (S.view !== 'project') {
    for (const p of D.projects) opts.push({ field: 'project', group: 'Project', value: p.slug, label: p.name });
    opts.push({ field: 'project', group: 'Project', value: 'none', label: 'No project' });
  }
  for (const o of opts) o.n = count(o.field, o.value);
  return opts.filter(o => o.n || S.f[o.field].includes(o.value));
}

function openFilter() {
  const pop = $('#popover');
  pop.innerHTML = '<input id="pop-input" placeholder="Filter by status, kind, area, project…" autocomplete="off"><div class="opts" id="pop-opts"></div>';
  pop.hidden = false;
  place(pop, $('#filter-btn'));
  const input = $('#pop-input');
  input.addEventListener('input', () => { popAt = 0; renderFilterOpts(); });
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { popAt = Math.min(popItems.length - 1, popAt + 1); highlightPop(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { popAt = Math.max(0, popAt - 1); highlightPop(); e.preventDefault(); }
    else if (e.key === 'Enter') { toggleFilter(popItems[popAt]); e.preventDefault(); }
    else if (e.key === 'Escape') { closePopover(); e.stopPropagation(); }
  });
  popAt = 0;
  renderFilterOpts();
  input.focus();
}

function renderFilterOpts() {
  const q = ($('#pop-input')?.value || '').toLowerCase().trim();
  const all = filterOptions();
  popItems = q ? all.filter(o => `${o.group} ${o.label}`.toLowerCase().includes(q)) : all;
  $('#pop-opts').innerHTML = popItems.map((o, n) => `<div class="opt" data-n="${n}"><span class="box${S.f[o.field].includes(o.value) ? ' yes' : ''}"></span><span class="grp">${esc(o.group)}</span>${o.icon || ''}<span class="t">${esc(o.label)}</span><span class="n">${o.n}</span></div>`).join('') || '<div class="empty" style="padding:20px">Nothing matches.</div>';
  highlightPop();
}

function highlightPop() {
  const opts = $('#pop-opts') || $('#popover .opts');
  if (!opts) return;
  opts.querySelectorAll('.opt.on').forEach(el => el.classList.remove('on'));
  const el = opts.querySelector(`[data-n="${popAt}"]`);
  el?.classList.add('on');
  el?.scrollIntoView({ block: 'nearest' });
}

function toggleFilter(o) {
  if (!o) return;
  if (o.hub) return switchHub(o.hub);
  const values = S.f[o.field].includes(o.value) ? S.f[o.field].filter(v => v !== o.value) : [...S.f[o.field], o.value];
  go({ f: { ...S.f, [o.field]: values } }, { replace: true });
  if (!$('#popover').hidden) renderFilterOpts();
}

function goView(view) { go({ view, slug: null, f: defaults().f, q: '' }); }

function clearFilters() { go({ f: defaults().f, q: '' }); }

function openDisplay() {
  const pop = $('#popover');
  const sel = (id, opts, cur) => `<select id="${id}">${Object.entries(opts).map(([k, v]) => `<option value="${k}"${k === cur ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select>`;
  pop.innerHTML = `<div class="display-pop"><label>Grouping ${sel('d-group', GROUPS, S.group)}</label><label>Ordering ${sel('d-order', ORDERS, S.order)}</label></div>`;
  pop.hidden = false;
  place(pop, $('#display-btn'));
  pop.style.left = `${Math.max(8, $('#display-btn').getBoundingClientRect().right - 280)}px`;
  $('#d-group').addEventListener('change', e => go({ group: e.target.value }));
  $('#d-order').addEventListener('change', e => go({ order: e.target.value }));
}

// ---------------------------------------------------------------- hubs

async function loadHubs() {
  if (HUB_SLUG) store.set('issue-hub:last', HUB_SLUG);
  try {
    const res = await fetch('../hubs.json', { cache: 'no-cache' });
    if (!res.ok) return;
    const list = await res.json();
    if (!Array.isArray(list)) return;
    HUBS = list;
  } catch { return; }
  const btn = $('#hub-switch');
  btn.classList.toggle('many', HUBS.length > 1);
  btn.disabled = HUBS.length < 2;
  btn.title = HUBS.length > 1 ? 'Switch hub (g h)' : '';
}

function switchHub(slug) {
  store.set('issue-hub:last', slug);
  location.href = `../${encodeURIComponent(slug)}/`;
}

function openHubs() {
  const pop = $('#popover');
  pop.innerHTML = `<div class="opts">${HUBS.map((h, n) => `<div class="opt hub-opt${h.slug === HUB_SLUG ? ' current' : ''}" data-hub="${esc(h.slug)}" data-n="${n}"><span class="hub-mark sm">${esc((h.name || '?').slice(0, 1).toUpperCase())}</span><span class="t">${esc(h.name)}</span><span class="n">${h.open} open</span></div>`).join('')}</div><a class="hub-all" href="../?pick">All hubs</a>`;
  pop.hidden = false;
  place(pop, $('#hub-switch'));
  popItems = HUBS.map(h => ({ hub: h.slug }));
  popAt = Math.max(0, HUBS.findIndex(h => h.slug === HUB_SLUG));
  highlightPop();
}

// ---------------------------------------------------------------- misc actions

function toggleTheme() {
  const root = document.documentElement;
  const current = root.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  root.dataset.theme = current === 'dark' ? 'light' : 'dark';
  store.set(THEME_KEY, root.dataset.theme);
}

let toastTimer = 0;
function toast(text) {
  const t = $('#toast');
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 1600);
}

function currentIssue() { return S.issue || (sel && !sel.startsWith('project:') ? sel : null); }

function copyLink() {
  const id = currentIssue();
  if (!id) return;
  const url = location.href.split('#')[0] + hashOf({ ...S, issue: id, open: null });
  navigator.clipboard?.writeText(url).then(() => toast(`Copied a link to ${id}`), () => toast(url));
}

function openPlan() {
  const id = currentIssue();
  const p = id ? projects.get(byId.get(id)?.projectSlug) : S.view === 'project' ? projects.get(S.slug) : null;
  if (p?.plan) openTarget('file:' + p.plan);
  else toast(p ? `${p.name} has no illustrated plan` : 'No project here');
}

function closeTop() {
  if (!$('#popover').hidden) return closePopover();
  if (!$('#palette').hidden) return closePalette();
  if (!$('#help').hidden) { $('#help').hidden = true; return; }
  if (S.open) return go({ open: null }, { replace: true });
  if (S.issue) { sel = S.issue; return go({ issue: null }, { replace: true }); }
  if ($('#app').classList.contains('nav-open')) return $('#app').classList.remove('nav-open');
  if (sel) { sel = null; markRows(); }
}

// ---------------------------------------------------------------- events

function handleOpenAttr(el) {
  const target = el.getAttribute('data-open');
  if (target) { openTarget(target); return true; }
  return false;
}

function interceptLink(a, e) {
  const href = a.getAttribute('href') || '';
  let m;
  if ((m = href.match(/^#([A-Z][A-Z0-9]*-\d+)$/))) { e.preventDefault(); sel = m[1]; go({ issue: m[1], open: null }); return; }
  if ((m = href.match(/^#project\/(.+)$/))) { e.preventDefault(); go({ view: 'project', slug: decodeURIComponent(m[1]), f: defaults().f, q: '', open: null }); return; }
  if ((m = href.match(/^#doc\/(.+)$/))) { e.preventDefault(); openTarget('doc:' + decodeURIComponent(m[1])); return; }
  if (href === '#board') { e.preventDefault(); go({ view: 'active', open: null }); return; }
  if (href.startsWith('hub/') && !e.metaKey && !e.ctrlKey) {
    const path = decodeURIComponent(href.slice(4).split('#')[0]);
    e.preventDefault();
    openTarget((path.endsWith('.md') ? 'page:' : 'file:') + path);
  }
}

function bind() {
  document.addEventListener('click', e => {
    const t = e.target;
    if (!$('#popover').hidden && !t.closest('#popover') && !t.closest('#filter-btn') && !t.closest('#display-btn') && !t.closest('#hub-switch')) closePopover();
    const open = t.closest('[data-open]');
    if (open) { e.preventDefault(); $('#app').classList.remove('nav-open'); handleOpenAttr(open); return; }
    const a = t.closest('a');
    if (a && (a.closest('.prose') || a.classList.contains('idlink'))) return interceptLink(a, e);
    if (a && a.closest('#nav')) { $('#app').classList.remove('nav-open'); }
    const filter = t.closest('[data-filter]');
    if (filter) {
      const field = filter.dataset.filter;
      const value = filter.dataset.value;
      const fromNav = !!filter.closest('#nav');
      const view = fromNav && (S.view === 'projects' || S.view === 'done') ? 'active' : S.view;
      const already = S.f[field].length === 1 && S.f[field][0] === value;
      go({ view, f: { ...defaults().f, ...(fromNav ? {} : S.f), [field]: already && fromNav ? [] : [value] } });
      $('#app').classList.remove('nav-open');
      return;
    }
    const issueBtn = t.closest('[data-issue]');
    if (issueBtn) { sel = issueBtn.dataset.issue; go({ issue: issueBtn.dataset.issue }, { replace: !!S.issue }); return; }
  });

  const content = $('#content');
  content.addEventListener('click', e => {
    const more = e.target.closest('[data-more]');
    if (more) { expanded.add(more.dataset.more); renderContent(); markRows(); return; }
    const head = e.target.closest('[data-group]');
    if (head) {
      const key = `${S.view}:${S.group}:${head.dataset.group}`;
      closed.has(key) ? closed.delete(key) : closed.add(key);
      store.set(KEY + ':closed', JSON.stringify([...closed]));
      renderContent(); markRows();
      return;
    }
    const row = e.target.closest('[data-id]');
    if (!row) return;
    sel = row.dataset.id;
    if (sel.startsWith('project:')) return openSelected();
    go({ issue: sel }, { replace: !!S.issue });
  });
  content.addEventListener('mouseover', e => {
    const row = e.target.closest('.row,.card');
    if (row) prefetch(row.dataset.id);
  });

  $('#peek').addEventListener('click', e => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'close') closeTop();
    else if (act === 'next') move(1);
    else if (act === 'prev') move(-1);
    else if (act === 'copy') copyLink();
  });

  $('#chips').addEventListener('click', e => {
    const b = e.target.closest('[data-chip]');
    if (!b) return;
    const c = chipGroups()[+b.dataset.chip];
    go({ f: { ...S.f, [c.field]: S.f[c.field].filter(v => !c.values.includes(v)) } });
  });

  let searchTimer = 0;
  $('#search').addEventListener('input', e => {
    clearTimeout(searchTimer);
    const value = e.target.value;
    searchTimer = setTimeout(() => go({ q: value }, { replace: true }), 30);
  });
  $('#search').addEventListener('keydown', e => {
    if (e.key === 'Escape') { if (e.target.value) { e.target.value = ''; go({ q: '' }, { replace: true }); } else e.target.blur(); e.stopPropagation(); }
    if (e.key === 'Enter' || e.key === 'ArrowDown') { e.preventDefault(); e.target.blur(); move(1); }
  });

  $('#palette-input').addEventListener('input', renderPalette);
  $('#palette-input').addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { paletteAt = Math.min(paletteItems.length - 1, paletteAt + 1); highlightPalette(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { paletteAt = Math.max(0, paletteAt - 1); highlightPalette(); e.preventDefault(); }
    else if (e.key === 'Enter') { runPalette(paletteAt); e.preventDefault(); }
    else if (e.key === 'Escape') { closePalette(); e.stopPropagation(); }
  });
  $('#palette-list').addEventListener('mousemove', e => {
    const it = e.target.closest('[data-n]');
    if (it && +it.dataset.n !== paletteAt) { paletteAt = +it.dataset.n; highlightPalette(); }
  });
  $('#palette-list').addEventListener('click', e => { const it = e.target.closest('[data-n]'); if (it) runPalette(+it.dataset.n); });
  $('#palette').addEventListener('mousedown', e => { if (e.target.id === 'palette') closePalette(); });
  $('#help').addEventListener('mousedown', e => { if (e.target.id === 'help') $('#help').hidden = true; });
  $('#viewer').addEventListener('mousedown', e => { if (e.target.id === 'viewer') go({ open: null }, { replace: true }); });
  $('#viewer-close').addEventListener('click', () => go({ open: null }, { replace: true }));
  $('#viewer-body').addEventListener('click', e => { const a = e.target.closest('.prose a'); if (a) interceptLink(a, e); });

  $('#popover').addEventListener('mousemove', e => {
    const it = e.target.closest('.opt');
    if (it && +it.dataset.n !== popAt) { popAt = +it.dataset.n; highlightPop(); }
  });
  $('#popover').addEventListener('click', e => { const it = e.target.closest('.opt'); if (it) toggleFilter(popItems[+it.dataset.n]); });

  $('#palette-open').addEventListener('click', openPalette);
  $('#hub-switch').addEventListener('click', () => { if (HUBS.length > 1) ($('#popover').hidden ? openHubs() : closePopover()); });
  $('#help-open').addEventListener('click', () => { $('#help').hidden = false; });
  $('#theme-toggle').addEventListener('click', toggleTheme);
  $('#filter-btn').addEventListener('click', () => ($('#popover').hidden ? openFilter() : closePopover()));
  $('#display-btn').addEventListener('click', () => ($('#popover').hidden ? openDisplay() : closePopover()));
  $('#layout-list').addEventListener('click', () => go({ layout: 'list' }));
  $('#layout-board').addEventListener('click', () => go({ layout: 'board' }));
  $('#menu-btn').addEventListener('click', () => $('#app').classList.toggle('nav-open'));
  $('#scrim').addEventListener('click', () => $('#app').classList.remove('nav-open'));

  addEventListener('popstate', () => apply(parseHash()));
  addEventListener('hashchange', () => { const next = parseHash(); if (hashOf(next) !== hashOf(S)) apply(next); });

  let gPending = 0;
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('#palette').hidden ? openPalette() : closePalette(); return; }
    const typing = e.target.closest('input,textarea,select');
    if (e.key === 'Escape' && !typing) { closeTop(); return; }
    if (typing || e.metaKey || e.ctrlKey || e.altKey || !D) return;
    if (!$('#palette').hidden) return;
    if (!$('#popover').hidden && $('#popover .hub-opt')) {
      if (e.key === 'ArrowDown' || e.key === 'j') { popAt = Math.min(popItems.length - 1, popAt + 1); highlightPop(); e.preventDefault(); return; }
      if (e.key === 'ArrowUp' || e.key === 'k') { popAt = Math.max(0, popAt - 1); highlightPop(); e.preventDefault(); return; }
      if (e.key === 'Enter') { toggleFilter(popItems[popAt]); e.preventDefault(); return; }
    }
    if (gPending) {
      clearTimeout(gPending); gPending = 0;
      const view = { a: 'active', b: 'backlog', l: 'all', d: 'done', p: 'projects' }[e.key];
      if (view) { e.preventDefault(); goView(view); }
      else if (e.key === 'h' && HUBS.length > 1) { e.preventDefault(); openHubs(); }
      return;
    }
    const keys = {
      j: () => move(1), ArrowDown: () => move(1), k: () => move(-1), ArrowUp: () => move(-1),
      Enter: openSelected, o: openSelected, '/': () => $('#search').focus(), f: openFilter, '?': () => { $('#help').hidden = false; },
      b: () => S.view !== 'projects' && go({ layout: S.layout === 'board' ? 'list' : 'board' }), x: clearFilters, c: copyLink, p: openPlan,
      g: () => { gPending = setTimeout(() => { gPending = 0; }, 900); },
    };
    if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
  });
}

// ---------------------------------------------------------------- start

function start() {
  bind();
  S = parseHash();
  const cached = store.get(KEY);
  if (cached) {
    try {
      const t = now();
      setData(JSON.parse(cached));
      apply({ ...S, __data: undefined });
      timings.push({ what: 'first paint from cache', ms: +(now() - t).toFixed(1) });
    } catch {}
  }
  if (!D) $('#content').innerHTML = '<div class="empty">Loading…</div>';
  refresh();
  loadHubs();
  setInterval(refresh, 60000);
  setInterval(freshness, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
}

start();
})();
