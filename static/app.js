'use strict';
/* Video Tile UI. Talks to the server only through `api` (mock.js provides
   window.mockApi for the prototype; without it the fetch-based api is used). */

/* ---------------- api ---------------- */
const realApi = (() => {
  const enc = encodeURIComponent;
  async function req(method, path, body) {
    const opt = { method, headers: {} };
    if (body instanceof FormData) opt.body = body;
    else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
    const r = await fetch(path, opt);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(data.error || `${r.status} ${r.statusText}`), { status: r.status, login: !!data.login });
    return data;
  }
  const form = (o) => { const f = new FormData(); for (const k in o) f.append(k, o[k]); return f; };
  const t0 = Date.now(), bust = {}; // cache-buster so a changed cover shows up
  const bumped = (key) => (r) => { bust[key] = Date.now(); return r; };
  return {
    config: () => req('GET', '/api/config'),
    ndLogin: (url, username, password) => req('POST', '/api/nd/login', { url, username, password }),
    ndLogout: () => req('POST', '/api/nd/logout'),
    ndPlaylists: () => req('GET', '/api/nd/playlists'),
    ndPlaylist: (id) => req('GET', `/api/nd/playlists/${enc(id)}`),
    ndSearch: (q) => req('GET', `/api/nd/search?q=${enc(q)}`),
    ytLookup: (url) => req('GET', `/api/yt/lookup?url=${enc(url)}`),
    addTrack: (source, ref) => req('POST', '/api/tracks', { source, ref }),
    uploadTrack: (file) => req('POST', '/api/tracks', form({ source: 'local', file })),
    track: (key) => req('GET', `/api/tracks/${enc(key)}`),
    peaks: (key) => req('GET', `/api/tracks/${enc(key)}/peaks`),
    audioUrl: (key) => `/api/tracks/${enc(key)}/audio`,
    coverUrl: (key, which) => `/api/tracks/${enc(key)}/cover?which=${which}&v=${bust[key] || t0}`,
    discogsSearch: (q) => req('GET', `/api/discogs/search?q=${enc(q)}`),
    discogsImages: (resourceUrl) => req('GET', `/api/discogs/images?resource_url=${enc(resourceUrl)}`),
    setCoverUrl: (key, url) => req('POST', `/api/tracks/${enc(key)}/cover`, { url }).then(bumped(key)),
    uploadCover: (key, file) => req('POST', `/api/tracks/${enc(key)}/cover`, form({ file })).then(bumped(key)),
    render: (payload) => req('POST', '/api/render', payload),
    job: (id) => req('GET', `/api/render/${enc(id)}`),
  };
})();
const api = window.mockApi || realApi;

/* ---------------- state ---------------- */
const LS_KEY = 'video-tile';
const STEPS = ['source', 'pick', 'clips', 'export'];
const state = { step: 'source', source: null, queue: [], length: 30, res: 1080 };
try { Object.assign(state, JSON.parse(localStorage.getItem(LS_KEY)) || {}); } catch {}
if (!STEPS.includes(state.step)) state.step = 'source';
state.queue = (state.queue || []).filter((t) => t && t.key); // drop half-finished adds
function persist() { try { localStorage.setItem(LS_KEY, JSON.stringify(state)); } catch {} }

// in-memory UI state (not persisted)
const ui = {
  config: null, ndTab: 'playlists', openPl: null, slots: new Map(),
  searchQ: '', searchRes: null, ytUrl: '', yt: null,
  pos: {}, peaks: new Map(), job: null, sheet: null,
};

/* ---------------- helpers ---------------- */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k in el && !k.includes('-')) el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  el.append(...kids.flat(Infinity).filter((c) => c != null && c !== false).map((c) => (c instanceof Node ? c : String(c))));
  return el;
}
const ICONS = {
  play: '<path d="M8 5.5v13l11-6.5z" fill="currentColor" stroke="none"/>',
  pause: '<path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" fill="currentColor" stroke="none"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  next: '<path d="M9 5l7 7-7 7"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  yt: '<rect x="2.5" y="5" width="19" height="14" rx="4"/><path d="M10 9.5v5l4.5-2.5z" fill="currentColor"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><circle cx="10.5" cy="16" r="2"/><path d="M12.5 16v-5.5l3 1"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5M5 20h14"/>',
  save: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
  flag: '<path d="M6 21V4M6 4h11l-2 4 2 4H6"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-5-5L5 21"/>',
};
function icon(name) {
  const t = document.createElement('template');
  t.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
  return t.content.firstChild;
}
const fmt = (s) => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const spinner = (text) => h('div', { class: 'empty' }, h('span', { class: 'status' }, h('span', { class: 'spin' }), text || 'Loading…'));
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
let toastTimer;
function toast(msg, ms = 2400) {
  const el = $('#toast'); el.textContent = msg; el.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), ms);
}
const fileName = (t) => (`${t.artist ? t.artist + ' - ' : ''}${t.title}`.replace(/[\\/:*?"<>|]+/g, '').trim().slice(0, 100) || 'clip');

/* ---------------- navigation ---------------- */
function go(step, extra) {
  if (step !== 'clips') audio.pause();
  state.step = step; persist();
  history.pushState({ step, ...extra }, '');
  render(); scrollTo(0, 0);
}
addEventListener('popstate', (e) => {
  const s = e.state || {};
  if (s.step && STEPS.includes(s.step)) { if (s.step !== 'clips') audio.pause(); state.step = s.step; persist(); }
  ui.openPl = s.pl || null;
  render();
});
$$('nav.steps button').forEach((b) => b.addEventListener('click', () => { if (b.dataset.step !== state.step) go(b.dataset.step); }));

function render() {
  const screen = { source: sourceScreen, pick: pickScreen, clips: clipsScreen, export: exportScreen }[state.step];
  $('#app').replaceChildren(...[screen()].flat(Infinity).filter(Boolean));
  renderBar();
  if (state.step === 'clips') paintAll();
}
function renderBar() {
  $$('nav.steps button').forEach((b) => {
    if (b.dataset.step === state.step) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current');
  });
  const badge = $('nav.steps .badge'), n = state.queue.length;
  badge.textContent = n; badge.hidden = !n;
}

/* ---------------- queue ---------------- */
const findQ = (source, ref) => state.queue.find((t) => t.source === source && t.ref === ref);
const isBusy = (t) => t.status === 'adding' || t.status === 'fetching';

function changed(item) {
  persist(); renderBar(); syncTicks();
  if (state.step === 'clips') { if (item) updateCard(item); else render(); }
  if (state.step === 'export') render();
  if (state.step === 'pick' && state.source === 'local') render();
}
function newItem(source, t) {
  return { key: null, source, ref: t.ref, title: t.title, artist: t.artist || '', album: t.album || '', status: 'adding', duration: t.duration || 0, start: 0, cover: 'default' };
}
async function enqueue(source, t) {
  if (findQ(source, t.ref)) return;
  const item = newItem(source, t);
  state.queue.push(item); changed();
  try { item.key = (await api.addTrack(source, t.ref)).key; item.status = 'fetching'; }
  catch (e) { item.status = 'failed'; item.error = e.message; }
  if (state.queue.includes(item)) changed(item);
}
async function uploadFiles(files) {
  for (const [i, file] of [...files].entries()) {
    const item = newItem('local', { ref: `${file.name}#${Date.now()}${i}`, title: file.name.replace(/\.[^.]+$/, '') });
    state.queue.push(item); changed();
    try { item.key = (await api.uploadTrack(file)).key; item.status = 'fetching'; }
    catch (e) { item.status = 'failed'; item.error = e.message; }
    if (state.queue.includes(item)) changed(item);
  }
}
function removeItem(item) {
  const i = state.queue.indexOf(item); if (i < 0) return;
  if (item.key && item.key === cur) { audio.pause(); audio.removeAttribute('src'); cur = null; }
  state.queue.splice(i, 1);
  const card = findCard(item);
  if (card && state.queue.length) { card.remove(); persist(); renderBar(); syncTicks(); return; }
  changed();
}
function toggleTrack(source, t) { const q = findQ(source, t.ref); q ? removeItem(q) : enqueue(source, t); }

// poll fetching tracks every 1.5 s
const inflight = new Set();
function checkTrack(item) {
  if (!item.key || inflight.has(item.key)) return;
  inflight.add(item.key);
  api.track(item.key).then((s) => {
    const before = item.status + item.duration;
    if (s.status === 'ready') { item.status = 'ready'; if (s.duration) item.duration = s.duration; delete item.error; }
    else if (s.status === 'failed') { item.status = 'failed'; item.error = s.error || 'Fetching failed'; }
    else if (s.status === 'missing') { item.status = 'failed'; item.error = 'Audio is no longer cached. Remove it and add it again.'; }
    else item.status = 'fetching';
    if (item.status === 'ready') loadPeaks(item);
    if (before !== item.status + item.duration && state.queue.includes(item)) changed(item);
  }).catch(() => {}).finally(() => inflight.delete(item.key));
}
setInterval(() => state.queue.forEach((t) => t.status === 'fetching' && checkTrack(t)), 1500);

/* ---------------- source ---------------- */
function sourceScreen(title) {
  const src = (id, ic, name, sub) => h('button', { class: 'src' + (state.source === id ? ' on' : ''), onclick: () => { state.source = id; go('pick'); } },
    icon(ic), h('div', { class: 'grow' }, h('b', {}, name), h('span', { class: 'muted small' }, sub)), icon('next'));
  return [
    h('h1', {}, title || 'Where’s the music?'),
    src('nd', 'server', 'Navidrome', 'Playlists and search in your library'),
    src('yt', 'yt', 'YouTube', 'A video or playlist link'),
    src('local', 'file', 'Local file', 'Audio files on this phone'),
    state.queue.length ? h('button', { class: 'btn ghost block', onclick: () => go('clips') }, `${plural(state.queue.length, 'track')} queued · Go to Clips`, icon('next')) : null,
  ];
}

/* ---------------- pick ---------------- */
function pickScreen() {
  if (!state.source) return sourceScreen('Choose a source first');
  return { nd: pickNd, yt: pickYt, local: pickLocal }[state.source]();
}

// async slot: loads once, re-renders Pick when done
function slot(name, fn) {
  if (!ui.slots.has(name)) {
    ui.slots.set(name, { loading: true });
    fn().then((data) => ui.slots.set(name, { data }), (e) => {
      if (e.login && ui.config) ui.config.nd_user = null;
      ui.slots.set(name, { error: e.message });
    }).then(() => state.step === 'pick' && render());
  }
  return ui.slots.get(name);
}
function slotView(s, fn) {
  if (s.loading) return spinner();
  if (s.error) return h('div', { class: 'empty' }, h('p', { class: 'err' }, s.error), h('button', { class: 'btn', onclick: () => { ui.slots.clear(); render(); } }, 'Try again'));
  return fn(s.data);
}

function trackRow(t, source, meta) {
  const on = !!findQ(source, t.ref);
  return h('button', { class: 'item', 'data-src': source, 'data-ref': t.ref, 'aria-pressed': String(on), onclick: () => toggleTrack(source, t) },
    h('div', { class: 't' },
      h('b', { class: 'ellip' }, t.title),
      h('span', { class: 'ellip' }, meta ?? [t.artist, t.album, t.duration ? fmt(t.duration) : ''].filter(Boolean).join(' · '))),
    h('span', { class: 'add' + (on ? ' on' : '') }, icon(on ? 'check' : 'plus')));
}
function addAllBtn(tracks, source) {
  const b = h('button', { class: 'btn primary', onclick: () => tracks.forEach((t) => enqueue(source, t)) });
  b._sync = () => {
    const left = tracks.filter((t) => !findQ(source, t.ref)).length;
    b.disabled = !left; b.replaceChildren(left ? icon('plus') : icon('check'), left ? (left === tracks.length ? `Add all ${left}` : `Add ${left} more`) : 'All added');
  };
  b._sync();
  return b;
}
function trackList(tracks, source, { title, back, addAll = true } = {}) {
  return h('div', {},
    (title || back || addAll) ? h('div', { class: 'list-head' },
      back ? h('button', { class: 'icon-btn', 'aria-label': 'Back', onclick: back }, icon('back')) : null,
      h('h2', { class: 'ellip' }, title || ''),
      addAll && tracks.length > 1 ? addAllBtn(tracks, source) : null) : null,
    tracks.length ? h('div', { class: 'list' }, tracks.map((t) => trackRow(t, source))) : h('div', { class: 'empty' }, 'Nothing here.'));
}
function syncTicks() {
  $$('.item[data-ref]').forEach((row) => {
    const on = !!findQ(row.dataset.src, row.dataset.ref), add = $('.add', row);
    if (!add || add.classList.contains('on') === on) return;
    row.setAttribute('aria-pressed', String(on));
    add.classList.toggle('on', on); add.replaceChildren(icon(on ? 'check' : 'plus'));
  });
  $$('.btn').forEach((b) => b._sync && b._sync());
}

function pickNd() {
  if (!ui.config) { loadConfig(); return [h('h1', {}, 'Navidrome'), spinner()]; }
  if (!ui.config.nd_user) return loginForm();
  const tab = (id, label) => h('button', { 'aria-pressed': String(ui.ndTab === id), onclick: () => { ui.ndTab = id; render(); } }, label);
  const head = h('div', { class: 'row' },
    h('h1', { class: 'grow' }, 'Navidrome'),
    h('button', { class: 'btn ghost', onclick: logout }, 'Log out'));
  let body;
  if (ui.ndTab === 'search') body = searchView();
  else if (ui.openPl) {
    const pl = ui.openPl;
    body = slotView(slot('pl:' + pl.id, () => api.ndPlaylist(pl.id)), (tracks) =>
      trackList(tracks, 'nd', { title: pl.name, back: () => (history.state && history.state.pl ? history.back() : ((ui.openPl = null), render())) }));
  } else {
    body = slotView(slot('playlists', api.ndPlaylists), (pls) => pls.length
      ? h('div', { class: 'list' }, pls.map((p) => h('button', { class: 'item', onclick: () => { ui.openPl = { id: p.id, name: p.name }; go('pick', { pl: ui.openPl }); } },
        h('div', { class: 't' }, h('b', { class: 'ellip' }, p.name), h('span', {}, plural(p.count, 'song'))), icon('next'))))
      : h('div', { class: 'empty' }, 'No playlists.'));
  }
  return [head, h('p', { class: 'muted small', style: 'margin-top:-12px' }, `Signed in as ${ui.config.nd_user}`),
    h('div', { class: 'seg', role: 'group' }, tab('playlists', 'Playlists'), tab('search', 'Search')), body];
}
function loginForm() {
  const err = h('p', { class: 'err', hidden: true });
  const btn = h('button', { class: 'btn primary block big', type: 'submit' }, 'Sign in');
  const f = h('form', {
    onsubmit: async (e) => {
      e.preventDefault();
      const d = new FormData(f);
      btn.disabled = true; btn.textContent = 'Signing in…'; err.hidden = true;
      try {
        const r = await api.ndLogin(d.get('url'), d.get('username'), d.get('password'));
        Object.assign(ui.config, { nd_user: r.user, nd_url: d.get('url') }); ui.slots.clear(); render();
      } catch (e2) { err.textContent = e2.message; err.hidden = false; btn.disabled = false; btn.textContent = 'Sign in'; }
    },
  },
  h('label', { class: 'field' }, h('span', {}, 'Server URL'), h('input', { type: 'url', name: 'url', value: ui.config.nd_url || '', required: true, autocomplete: 'url', inputmode: 'url' })),
  h('label', { class: 'field' }, h('span', {}, 'Username'), h('input', { type: 'text', name: 'username', required: true, autocomplete: 'username', autocapitalize: 'none', spellcheck: false })),
  h('label', { class: 'field' }, h('span', {}, 'Password'), h('input', { type: 'password', name: 'password', autocomplete: 'current-password' })),
  err, btn);
  return [h('h1', {}, 'Sign in to Navidrome'), f];
}
function logout() {
  api.ndLogout().catch(() => {}).then(() => { ui.config.nd_user = null; ui.slots.clear(); ui.openPl = null; ui.searchRes = null; render(); });
}
let searchTimer, searchSeq = 0;
function searchView() {
  const results = h('div', {});
  const show = () => {
    const r = ui.searchRes;
    if (!r || !ui.searchQ.trim()) results.replaceChildren(h('div', { class: 'empty' }, 'Type to search songs.'));
    else if (r.loading) results.replaceChildren(spinner('Searching…'));
    else if (r.error) results.replaceChildren(h('p', { class: 'err' }, r.error));
    else results.replaceChildren(trackList(r.data, 'nd', { addAll: false }));
  };
  const run = (q) => {
    const seq = ++searchSeq;
    ui.searchRes = { loading: true }; show();
    api.ndSearch(q).then((data) => ({ data }), (e) => {
      if (e.login) { ui.config.nd_user = null; render(); }
      return { error: e.message };
    }).then((r) => { if (seq === searchSeq) { ui.searchRes = r; if (results.isConnected) show(); } });
  };
  const input = h('input', {
    type: 'search', placeholder: 'Song, artist or album', value: ui.searchQ, enterkeyhint: 'search', 'aria-label': 'Search songs',
    oninput: () => {
      ui.searchQ = input.value; clearTimeout(searchTimer);
      if (!input.value.trim()) { searchSeq++; ui.searchRes = null; show(); return; }
      searchTimer = setTimeout(() => run(input.value.trim()), 300);
    },
    onkeydown: (e) => e.key === 'Enter' && input.blur(),
  });
  show();
  return h('div', {}, h('div', { style: 'margin-bottom:12px' }, input), results);
}

function pickYt() {
  const input = h('input', { type: 'url', name: 'url', placeholder: 'https://youtube.com/watch?v=…', value: ui.ytUrl, required: true, inputmode: 'url', enterkeyhint: 'go', 'aria-label': 'YouTube URL', oninput: () => { ui.ytUrl = input.value; } });
  const lookup = async (e) => {
    e.preventDefault();
    const url = input.value.trim(); if (!url) return;
    input.blur();
    ui.yt = { loading: true }; render();
    try {
      const r = await api.ytLookup(url);
      ui.yt = { data: r };
      if (r.tracks.length === 1) { enqueue('yt', r.tracks[0]); toast('Added to clips'); }
    } catch (err) { ui.yt = { error: err.message }; }
    if (state.step === 'pick' && state.source === 'yt') render();
  };
  const y = ui.yt;
  let result = null;
  if (y && y.loading) result = spinner('Looking up…');
  else if (y && y.error) result = h('p', { class: 'err' }, y.error);
  else if (y && y.data) result = y.data.tracks.length === 1
    ? trackList(y.data.tracks, 'yt', { title: 'Added', addAll: false })
    : trackList(y.data.tracks, 'yt', { title: y.data.title });
  return [
    h('h1', {}, 'YouTube'),
    h('form', { class: 'row', style: 'margin-bottom:20px', novalidate: true, onsubmit: lookup }, input, h('button', { class: 'btn primary', type: 'submit', style: 'min-height:48px' }, 'Look up')),
    result || h('p', { class: 'muted small' }, 'Paste a video link to add it, or a playlist link to choose from its videos.'),
  ];
}

function pickLocal() {
  const mine = state.queue.filter((t) => t.source === 'local');
  const st = (t) => ({ adding: 'Uploading…', fetching: 'Processing…', failed: t.error || 'Failed' }[t.status] || fmt(t.duration));
  return [
    h('h1', {}, 'Local file'),
    h('label', { class: 'drop' },
      icon('upload'), h('b', {}, 'Choose audio files'), h('span', { class: 'muted small' }, 'MP3, FLAC, M4A, WAV… from this phone'),
      h('input', { type: 'file', accept: 'audio/*', multiple: true, onchange: (e) => { uploadFiles(e.target.files); e.target.value = ''; } })),
    mine.length ? h('div', {}, h('div', { class: 'list-head' }, h('h2', {}, 'Added from this phone')),
      h('div', { class: 'list' }, mine.map((t) => trackRow(t, 'local', st(t))))) : null,
  ];
}

/* ---------------- clips ---------------- */
const audio = new Audio();
audio.preload = 'auto';
let cur = null, previewEnd = null, ticking = false; // key loaded in <audio>; end time when previewing the clip

function play(item, from) {
  const key = item.key;
  if (from == null && cur === key && !audio.paused) { audio.pause(); return; }
  if (cur !== key) { audio.pause(); audio.src = api.audioUrl(key); cur = key; }
  const t = from ?? ui.pos[key] ?? item.start;
  previewEnd = from != null ? from + state.length : null;
  const seekThen = () => { audio.currentTime = t; };
  if (audio.readyState >= 1) seekThen(); else audio.addEventListener('loadedmetadata', seekThen, { once: true });
  audio.play().catch((e) => e.name !== 'AbortError' && toast('Playback failed: ' + e.message));
}
function tick() {
  if (!cur || audio.paused) { ticking = false; return; }
  ui.pos[cur] = audio.currentTime;
  if (previewEnd != null && audio.currentTime >= previewEnd) {
    audio.pause(); previewEnd = null;
    const it = state.queue.find((t) => t.key === cur);
    if (it) { ui.pos[cur] = it.start; audio.currentTime = it.start; }
  }
  paintKey(cur);
  requestAnimationFrame(tick);
}
audio.addEventListener('play', () => { if (!ticking) { ticking = true; requestAnimationFrame(tick); } syncPlayButtons(); });
audio.addEventListener('pause', syncPlayButtons);
audio.addEventListener('ended', () => { previewEnd = null; syncPlayButtons(); });
audio.addEventListener('error', () => { if (audio.getAttribute('src')) toast('Couldn’t load the audio'); });
function syncPlayButtons() {
  $$('.card').forEach((c) => {
    const b = $('.play', c); if (!b) return;
    const playing = c._item.key === cur && !audio.paused;
    b.replaceChildren(icon(playing ? 'pause' : 'play')); b.setAttribute('aria-label', playing ? 'Pause' : 'Play');
  });
}

function loadPeaks(item) {
  if (!item.key || ui.peaks.has(item.key)) return;
  ui.peaks.set(item.key, 'loading');
  api.peaks(item.key).then((p) => ui.peaks.set(item.key, p), () => ui.peaks.set(item.key, 'error')).then(() => paintKey(item.key));
}

function clipsScreen() {
  const lengthIn = h('input', {
    type: 'number', min: 1, max: 600, step: 1, inputmode: 'numeric', value: state.length,
    oninput: () => { const v = parseInt(lengthIn.value, 10); if (v > 0) { state.length = Math.min(600, v); persist(); paintAll(); } },
    onchange: () => { lengthIn.value = state.length; },
  });
  const resIn = h('select', { onchange: () => { state.res = +resIn.value; persist(); } },
    [720, 1080].map((r) => h('option', { value: r, selected: state.res === r }, `${r} × ${r}`)));
  const out = [
    h('h1', {}, 'Clips'),
    h('div', { class: 'settings' },
      h('label', { class: 'field' }, h('span', {}, 'Length (s)'), lengthIn),
      h('label', { class: 'field' }, h('span', {}, 'Resolution'), resIn)),
  ];
  if (!state.queue.length) {
    out.push(h('div', { class: 'empty' }, h('p', {}, 'No tracks yet.'), h('button', { class: 'btn primary', onclick: () => go(state.source ? 'pick' : 'source') }, 'Pick tracks')));
    return out;
  }
  out.push(h('p', { class: 'muted small' }, 'Tap or drag the waveform to move the playhead, then Set start here.'));
  out.push(h('div', { id: 'cards' }, state.queue.map(cardEl)));
  return out;
}

function cardEl(item) {
  const removeBtn = h('button', { class: 'icon-btn', 'aria-label': 'Remove', onclick: () => removeItem(item) }, icon('x'));
  const meta = [item.artist, item.album].filter(Boolean).join(' · ');
  if (item.status === 'failed') {
    const c = h('div', { class: 'card failed' }, h('div', { class: 'card-head' },
      h('div', { class: 't' }, h('b', { class: 'ellip' }, item.title), meta ? h('span', { class: 'ellip' }, meta) : null,
        h('span', { class: 'err' }, item.error || 'Failed')),
      removeBtn));
    c._item = item;
    return c;
  }
  const ready = item.status === 'ready';
  const thumb = item.key
    ? h('button', { class: 'thumb', 'aria-label': 'Change cover', onclick: () => openSheet(item) },
      h('img', { src: api.coverUrl(item.key, item.cover), alt: '', loading: 'lazy' }), h('i', {}, icon('edit')))
    : h('div', { class: 'thumb' });
  const status = !ready ? h('span', { class: 'status' }, h('span', { class: 'spin' }), item.status === 'adding' ? 'Adding…' : 'Fetching audio…') : null;
  const cv = h('canvas', {});
  const wave = h('div', { class: 'wave' }, cv, h('div', { class: 'ph' }, 'building waveform…'), h('div', { class: 'tm' }));
  if (ready) waveInput(wave, item);
  const card = h('div', { class: 'card' },
    h('div', { class: 'card-head' }, thumb,
      h('div', { class: 't' }, h('b', { class: 'ellip' }, item.title), meta ? h('span', { class: 'ellip' }, meta) : null, status),
      removeBtn),
    wave,
    h('div', { class: 'controls' },
      h('button', { class: 'play', 'aria-label': 'Play', disabled: !ready, onclick: () => play(item) }, icon('play')),
      h('button', { class: 'btn setstart', disabled: !ready, onclick: () => setStart(item) }, icon('flag'), 'Set start here'),
      h('span', { class: 'grow' }),
      h('button', { class: 'chip', disabled: !ready, onclick: () => play(item, item.start) }, icon('play'), h('span', {}, `Start ${fmt(item.start)}`))));
  card._item = item;
  if (ready) loadPeaks(item);
  return card;
}
function findCard(item) { return $$('.card').find((c) => c._item === item); }
function updateCard(item) {
  const old = findCard(item);
  if (!old) { if (state.queue.includes(item) && $('#cards')) $('#cards').append(cardEl(item)); else if (!$('#cards')) render(); paintKey(item.key); return; }
  old.replaceWith(cardEl(item)); paintItem(item); syncPlayButtons();
}
function setStart(item) {
  const d = durOf(item);
  let t = ui.pos[item.key] ?? item.start;
  if (d) t = Math.min(t, Math.max(0, d - 1));
  item.start = Math.round(t * 10) / 10; persist(); paintItem(item);
  toast(`Clip starts at ${fmt(item.start)}`, 1400);
}
const durOf = (item) => item.duration || (item.key === cur && isFinite(audio.duration) ? audio.duration : 0);

function seek(item, t) {
  const d = durOf(item); if (!d) return;
  t = Math.max(0, Math.min(d, t));
  ui.pos[item.key] = t;
  if (cur === item.key && audio.readyState >= 1) { audio.currentTime = t; if (previewEnd != null && t < item.start) previewEnd = null; }
  paintItem(item);
}
// tap or horizontal drag seeks; vertical swipes still scroll the page (touch-action: pan-y)
function waveInput(wave, item) {
  let down = null;
  const at = (e) => { const r = wave.getBoundingClientRect(); return ((e.clientX - r.left) / r.width) * durOf(item); };
  wave.addEventListener('pointerdown', (e) => { down = { x: e.clientX, drag: false }; wave.setPointerCapture(e.pointerId); });
  wave.addEventListener('pointermove', (e) => {
    if (!down) return;
    if (!down.drag && Math.abs(e.clientX - down.x) > 6) down.drag = true;
    if (down.drag) seek(item, at(e));
  });
  wave.addEventListener('pointerup', (e) => { if (down) seek(item, at(e)); down = null; });
  wave.addEventListener('pointercancel', () => { down = null; });
}

let colors = null;
const readColors = () => {
  const cs = getComputedStyle(document.documentElement), v = (n) => cs.getPropertyValue(n).trim();
  colors = { accent: v('--accent'), wave: v('--wave'), clip: v('--clip'), text: v('--text') };
};
matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => { readColors(); paintAll(); });

// after tdz refine.js paintWave: 2× canvas, one bar per CSS px, played part in accent, playhead line
function paintWave(card, item) {
  const cv = $('canvas', card), ph = $('.ph', card); if (!cv) return;
  const w = cv.clientWidth, hgt = cv.clientHeight; if (!w) return;
  if (cv.width !== w * 2 || cv.height !== hgt * 2) { cv.width = w * 2; cv.height = hgt * 2; }
  const g = cv.getContext('2d'); g.setTransform(2, 0, 0, 2, 0, 0); g.clearRect(0, 0, w, hgt);
  if (!colors) readColors();
  const peaks = ui.peaks.get(item.key), ok = Array.isArray(peaks);
  ph.hidden = ok;
  ph.textContent = peaks === 'error' ? 'waveform unavailable' : 'building waveform…';
  if (!ok) return;
  const d = durOf(item), pos = ui.pos[item.key] ?? item.start, done = d ? Math.min(1, pos / d) : 0;
  if (d) { // clip window: start → start + length
    const a = (item.start / d) * w, b = Math.min(1, (item.start + state.length) / d) * w;
    g.globalAlpha = 0.22; g.fillStyle = colors.clip; g.fillRect(a, 0, b - a, hgt);
    g.globalAlpha = 1; g.fillRect(a, 0, 2, hgt); g.fillRect(b - 1, 0, 1, hgt);
  }
  const N = peaks.length;
  for (let x = 0; x < w; x++) {
    const v = peaks[Math.floor((x / w) * N)] || 0, bh = Math.max(1, v * (hgt - 10));
    g.fillStyle = x / w < done ? colors.accent : colors.wave;
    g.fillRect(x, (hgt - bh) / 2, 1, bh);
  }
  if (d) { g.fillStyle = colors.text; g.fillRect(Math.min(w - 2, done * w), 0, 2, hgt); }
}
function paintItem(item) {
  const card = findCard(item); if (!card || item.status !== 'ready') return;
  paintWave(card, item);
  const pos = ui.pos[item.key] ?? item.start;
  $('.tm', card).textContent = `${fmt(pos)} / ${fmt(durOf(item))}`;
  const chip = $('.chip', card);
  $('span', chip).textContent = `Start ${fmt(item.start)}`;
  chip.setAttribute('aria-label', `Preview clip from ${fmt(item.start)}`);
}
function paintKey(key) { const it = state.queue.find((t) => t.key === key); if (it) paintItem(it); }
function paintAll() { state.queue.forEach(paintItem); }
let resizeTimer;
addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(paintAll, 100); });

/* ---------------- cover sheet ---------------- */
const sheet = $('#sheet');
sheet.addEventListener('click', (e) => { if (e.target === sheet) sheet.close(); });
sheet.addEventListener('close', () => { ui.sheet = null; });

function openSheet(item) {
  ui.sheet = { item, tab: 'default', q: [item.artist, item.album].filter(Boolean).join(' ') || item.title, results: null, release: null, busy: false };
  renderSheet(); sheet.showModal();
  $('.sheet-body', sheet).scrollTop = 0;
}
function renderSheet() {
  const s = ui.sheet; if (!s) return;
  const it = s.item, discogs = !!(ui.config && ui.config.discogs);
  const tab = (id, label) => h('button', { 'aria-pressed': String(s.tab === id), onclick: () => { s.tab = id; renderSheet(); } }, label);
  const body = { default: coverDefault, discogs: coverDiscogs, url: coverUrlTab, upload: coverUpload }[s.tab](s, discogs);
  sheet.replaceChildren(
    h('div', { class: 'grab' }),
    h('div', { class: 'sheet-head' },
      h('div', { class: 'thumb' }, h('img', { src: api.coverUrl(it.key, it.cover), alt: '' })),
      h('div', { class: 't' }, h('b', { class: 'ellip' }, 'Cover'), h('span', { class: 'ellip' }, it.title)),
      h('button', { class: 'icon-btn', 'aria-label': 'Close', onclick: () => sheet.close() }, icon('x'))),
    h('div', { class: 'sheet-tabs' }, h('div', { class: 'seg', role: 'group' },
      tab('default', 'Default'), discogs ? tab('discogs', 'Discogs') : null, tab('url', 'URL'), tab('upload', 'Upload'))),
    h('div', { class: 'sheet-body' }, body));
}
async function chooseCover(fn) {
  const s = ui.sheet; if (!s || s.busy) return;
  s.busy = true; renderSheet();
  try {
    await fn();
    s.item.cover = 'custom'; persist(); updateCard(s.item); sheet.close(); toast('Cover updated');
  } catch (e) { s.busy = false; s.error = e.message; renderSheet(); }
}
const busyOr = (s, node) => (s.busy ? spinner('Saving cover…') : node);
const errLine = (s) => (s.error ? h('p', { class: 'err', style: 'margin-top:8px' }, s.error) : null);

function coverDefault(s, discogs) {
  const it = s.item, isDefault = it.cover === 'default';
  return [
    h('img', { class: 'big-cover', src: api.coverUrl(it.key, 'default'), alt: 'Default cover' }),
    h('button', {
      class: 'btn block big' + (isDefault ? '' : ' primary'), disabled: isDefault,
      onclick: () => { it.cover = 'default'; persist(); updateCard(it); sheet.close(); toast('Using the default cover'); },
    }, isDefault ? [icon('check'), 'Using the default cover'] : 'Use the default cover'),
    discogs ? null : h('p', { class: 'note' }, 'Discogs search isn’t configured on the server (DISCOGS_TOKEN), so its tab is hidden.'),
  ];
}
function coverDiscogs(s) {
  const input = h('input', { type: 'search', value: s.q, enterkeyhint: 'search', 'aria-label': 'Discogs search', oninput: () => { s.q = input.value; } });
  const search = (e) => {
    if (e) e.preventDefault();
    const q = s.q.trim(); if (!q) return;
    input.blur();
    s.results = { loading: true }; s.release = null; renderSheet();
    api.discogsSearch(q).then((data) => ({ data }), (err) => ({ error: err.message }))
      .then((r) => { if (ui.sheet === s) { s.results = r; renderSheet(); } });
  };
  if (!s.results && s.q.trim()) setTimeout(search); // auto-search the prefilled query
  const form = h('form', { class: 'row', style: 'margin-bottom:12px', onsubmit: search }, input,
    h('button', { class: 'btn primary', type: 'submit', 'aria-label': 'Search', style: 'min-height:48px' }, icon('search')));
  let body = null;
  if (s.release) {
    const rel = s.release;
    body = h('div', {},
      h('div', { class: 'list-head' }, h('button', { class: 'icon-btn', 'aria-label': 'Back to results', onclick: () => { s.release = null; renderSheet(); } }, icon('back')),
        h('h2', { class: 'ellip' }, rel.title)),
      rel.loading ? spinner() : rel.error ? h('p', { class: 'err' }, rel.error)
        : h('div', { class: 'grid' }, rel.images.map((url) => h('button', { class: 'tile', onclick: () => chooseCover(() => api.setCoverUrl(s.item.key, url)) },
          h('img', { src: url, alt: '', loading: 'lazy' })))));
  } else if (s.results) {
    const r = s.results;
    body = r.loading ? spinner('Searching Discogs…') : r.error ? h('p', { class: 'err' }, r.error)
      : !r.data.length ? h('div', { class: 'empty' }, 'No releases found.')
        : h('div', { class: 'grid' }, r.data.map((res) => h('button', {
          class: 'tile',
          onclick: () => {
            const rel = { title: res.title, loading: true }; s.release = rel; renderSheet();
            api.discogsImages(res.resource_url).then((images) => Object.assign(rel, { loading: false, images }), (err) => Object.assign(rel, { loading: false, error: err.message }))
              .then(() => { if (s.release === rel) renderSheet(); });
          },
        }, h('img', { src: res.thumb, alt: '', loading: 'lazy' }), h('span', { class: 'ellip' }, res.title), h('span', {}, res.year))));
  }
  return [form, busyOr(s, body), errLine(s)];
}
function coverUrlTab(s) {
  const input = h('input', { type: 'url', placeholder: 'https://…/cover.jpg', inputmode: 'url', 'aria-label': 'Image URL', required: true });
  return busyOr(s, [h('form', {
    onsubmit: (e) => { e.preventDefault(); const url = input.value.trim(); if (url) chooseCover(() => api.setCoverUrl(s.item.key, url)); },
  }, h('label', { class: 'field' }, h('span', {}, 'Image URL'), input), h('button', { class: 'btn primary block big', type: 'submit' }, 'Use this image')), errLine(s)]);
}
function coverUpload(s) {
  return busyOr(s, [h('label', { class: 'drop' }, icon('image'), h('b', {}, 'Choose an image'), h('span', { class: 'muted small' }, 'From your photos or files'),
    h('input', { type: 'file', accept: 'image/*', onchange: (e) => { const f = e.target.files[0]; if (f) chooseCover(() => api.uploadCover(s.item.key, f)); } })), errLine(s)]);
}

/* ---------------- export ---------------- */
function exportScreen() {
  const q = state.queue, ready = q.filter((t) => t.status === 'ready'), busy = q.filter(isBusy), failed = q.filter((t) => t.status === 'failed');
  const job = ui.job, jobItems = job ? job.items : [], byKey = new Map(jobItems.map((j) => [j.key, j]));
  const running = jobItems.some((j) => j.status === 'queued' || j.status === 'rendering');
  const done = jobItems.filter((j) => j.status === 'done');
  const canShare = !!navigator.canShare;

  const notes = [busy.length ? `${busy.length} still fetching` : '', failed.length ? `${failed.length} failed (skipped)` : ''].filter(Boolean).join(' · ');
  const renderLabel = running ? `Rendering ${done.length + 1} of ${jobItems.length}…` : job ? 'Render again' : `Render ${plural(ready.length, 'clip')}`;
  const out = [
    h('h1', {}, 'Export'),
    h('div', { class: 'summary' },
      h('b', {}, `${plural(ready.length, 'clip')} · ${state.length} s · ${state.res}×${state.res}`),
      notes ? h('span', { class: 'muted small' }, notes) : null),
    h('div', { class: 'actions' },
      h('button', { class: 'btn primary block big', disabled: running || !!busy.length || !ready.length, onclick: startRender },
        running ? h('span', { class: 'spin' }) : null, renderLabel),
      job && !running && done.length > 1 ? h('button', { class: 'btn block big', onclick: () => saveFiles(done) }, icon('save'), `Save all ${done.length}`) : null,
      busy.length ? h('p', { class: 'muted small', style: 'margin:0' }, 'Render unlocks when every track has finished fetching.') : null,
      done.length && !canShare ? h('p', { class: 'note', style: 'margin:0' }, 'Sharing to apps needs HTTPS, so Save downloads the files instead.') : null),
  ];
  if (!q.length) { out.push(h('div', { class: 'empty' }, 'Nothing to export yet.')); return out; }
  out.push(h('div', { class: 'list' }, q.map((t) => {
    const j = byKey.get(t.key);
    let right;
    if (t.status === 'failed') right = h('span', { class: 'pill failed' }, 'Failed');
    else if (isBusy(t)) right = h('span', { class: 'pill' }, h('span', { class: 'spin' }), 'Fetching');
    else if (!j) right = h('span', { class: 'pill' }, job ? 'Not rendered' : 'Ready');
    else if (j.status === 'queued') right = h('span', { class: 'pill' }, 'Queued');
    else if (j.status === 'rendering') right = h('span', { class: 'pill' }, h('span', { class: 'spin' }), 'Rendering');
    else if (j.status === 'failed') right = h('span', { class: 'pill failed', title: j.error || '' }, 'Failed');
    else right = h('button', { class: 'btn', disabled: !j.fetched, onclick: () => saveFiles([j]) }, j.fetched ? icon('save') : h('span', { class: 'spin' }), 'Save');
    const sub = j && j.status === 'failed' && j.error ? j.error : `${t.artist ? t.artist + ' · ' : ''}from ${fmt(t.start)}`;
    return h('div', { class: 'item' }, h('div', { class: 't' }, h('b', { class: 'ellip' }, t.title), h('span', { class: 'ellip' + (j && j.status === 'failed' ? ' err' : '') }, sub)), right);
  })));
  return out;
}

async function startRender() {
  const ready = state.queue.filter((t) => t.status === 'ready');
  const items = ready.map((t) => ({ key: t.key, start: t.start, cover: t.cover, name: fileName(t) }));
  const job = { id: null, items: items.map((i) => ({ key: i.key, name: i.name, status: 'queued' })) };
  ui.job = job; render();
  try { job.id = (await api.render({ length: state.length, res: state.res, items })).job; pollJob(job); }
  catch (e) { if (ui.job === job) ui.job = null; toast(e.message); render(); }
}
function pollJob(job) {
  if (ui.job !== job) return;
  api.job(job.id).then((r) => {
    if (ui.job !== job) return;
    let moved = false;
    r.items.forEach((ri) => {
      const j = job.items.find((x) => x.key === ri.key); if (!j) return;
      if (j.status !== ri.status) moved = true;
      Object.assign(j, ri);
      if (ri.status === 'done' && ri.url && !j.prefetching) prefetch(j);
    });
    const left = job.items.some((j) => j.status === 'queued' || j.status === 'rendering');
    if (moved && state.step === 'export') render();
    if (left) setTimeout(() => pollJob(job), 1000);
    else toast(`Rendered ${plural(job.items.filter((j) => j.status === 'done').length, 'clip')}`);
  }).catch((e) => { toast(e.message); setTimeout(() => pollJob(job), 3000); });
}
// fetch the finished file now, so Save can call navigator.share() straight from the tap
function prefetch(j) {
  j.prefetching = true;
  fetch(j.url).then((r) => r.blob()).then((b) => { j.file = new File([b], `${j.name}.mp4`, { type: 'video/mp4' }); }, () => {})
    .then(() => { j.fetched = true; if (state.step === 'export') render(); });
}
async function saveFiles(items) {
  const files = items.map((j) => j.file).filter(Boolean);
  if (files.length === items.length && navigator.canShare && navigator.canShare({ files })) {
    try { await navigator.share({ files }); } catch (e) { if (e.name !== 'AbortError') toast(e.message); }
    return;
  }
  items.forEach((j, i) => setTimeout(() => {
    const a = h('a', { href: j.url, download: `${j.name}.mp4` });
    document.body.append(a); a.click(); a.remove();
  }, i * 400));
}

/* ---------------- start ---------------- */
function loadConfig() {
  if (loadConfig.p) return loadConfig.p;
  loadConfig.p = api.config().then((c) => { ui.config = c; }, (e) => {
    ui.config = { nd_url: '', nd_user: null, discogs: false }; toast('Server unreachable: ' + e.message);
  }).then(() => { if (state.step === 'pick') render(); });
  return loadConfig.p;
}
history.replaceState({ step: state.step }, '');
loadConfig();
state.queue.forEach((t) => t.status !== 'failed' && checkTrack(t)); // re-check after a reload
render();
