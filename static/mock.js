/* Mock API for the UI prototype. Same methods and JSON shapes as the real
   backend (see api-contract). Delete this file (or stop loading it) and
   app.js falls back to the real fetch-based api. */
(() => {
  const wait = (v) => new Promise((ok) => setTimeout(() => ok(v), 300 + Math.random() * 500));
  const copy = (v) => JSON.parse(JSON.stringify(v));
  const reply = (v) => wait(copy(v));
  const fail = (msg, extra) => wait().then(() => { throw Object.assign(new Error(msg), extra || {}); });

  // tiny deterministic PRNG so fixtures and peaks are stable across reloads
  const hash = (s) => { let x = 2166136261; for (const c of String(s)) x = Math.imul(x ^ c.charCodeAt(0), 16777619); return x >>> 0; };
  const rng = (seed) => () => { seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t ^= t + Math.imul(t ^ (t >>> 7), 61 | t); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const pick = (r, a) => a[Math.floor(r() * a.length)];

  const ARTISTS = ['Moonfield', 'The Paper Lanterns', 'Ola Vint', 'Kestrel Bay', 'Night Signals', 'Juniper & Ash', 'Low Tide Choir', 'Marisol Reyes', 'Static Gardens', 'Hollow Pines'];
  const WORDS = ['Neon', 'Harbor', 'Glass', 'Summer', 'Echo', 'Velvet', 'Midnight', 'Paper', 'Golden', 'Satellite', 'River', 'Ghost', 'Silver', 'Wild', 'Northern', 'Quiet'];
  const NOUNS = ['Lights', 'Heart', 'Highway', 'Rain', 'Season', 'Signal', 'Garden', 'Coast', 'Dream', 'Hours', 'Fire', 'Waves', 'Static', 'Avenue'];
  const ALBUMS = ['Blue Hour', 'Field Recordings', 'Second Nature', 'After the Flood', 'Small Rooms', 'Long Way Home'];

  const songs = (seed, n, prefix) => {
    const r = rng(hash(seed));
    return Array.from({ length: n }, (_, i) => ({
      ref: `${prefix}${hash(seed + i).toString(36)}`,
      title: `${pick(r, WORDS)} ${pick(r, NOUNS)}`,
      artist: pick(r, ARTISTS),
      album: pick(r, ALBUMS),
      duration: Math.round(150 + r() * 140), // ≤ 290 s so the mock audio covers it
    }));
  };

  const PLAYLISTS = [
    { id: 'pl1', name: 'Late Night Drive', tracks: songs('late', 25, 'nd-') },
    { id: 'pl2', name: 'Sunday Morning', tracks: songs('sunday', 8, 'nd-') },
    { id: 'pl3', name: 'Gym Rotation', tracks: songs('gym', 12, 'nd-') },
    { id: 'pl4', name: 'Fresh Finds', tracks: songs('fresh', 6, 'nd-') },
  ];
  // one track that always fails to fetch
  Object.assign(PLAYLISTS[0].tracks[6], { ref: 'nd-broken', title: 'Broken Stream', artist: 'Unknown Artist' });

  const known = new Map(); // ref -> Track, so addTrack knows durations
  const remember = (list) => { list.forEach((t) => known.set(t.ref, t)); return list; };
  PLAYLISTS.forEach((p) => remember(p.tracks));

  const LS = 'vt-mock-user'; // mock keeps the login across reloads, like the real session cookie
  const lsGet = () => { try { return localStorage.getItem(LS); } catch { return null; } };
  const lsSet = (v) => { try { v ? localStorage.setItem(LS, v) : localStorage.removeItem(LS); } catch {} };

  const cfg = { nd_url: 'http://navidrome:4533', nd_user: lsGet(), discogs: true };
  const tracks = new Map(); // key -> {status, readyAt, duration, error?}
  const covers = new Map(); // key -> custom cover url
  const audio = new Map(); // key -> object url
  const localAudio = new Map(); // key -> object url of the uploaded file
  const jobs = new Map();
  let jobN = 0, brokenOutputs = false;

  const needLogin = () => !cfg.nd_user && fail('Not signed in to Navidrome', { status: 401, login: true });
  const guessDuration = (key) => 150 + (hash(key) % 140);

  const startFetch = (key, duration, error) => {
    if (!tracks.has(key)) tracks.set(key, { status: 'fetching', readyAt: Date.now() + 1500, duration, error });
    return reply({ key });
  };

  function trackState(key) {
    const t = tracks.get(key);
    if (!t) return { status: 'ready', duration: guessDuration(key) }; // unknown after reload → ready
    if (t.status === 'fetching' && Date.now() >= t.readyAt) t.status = t.error ? 'failed' : 'ready';
    if (t.status === 'failed') return { status: 'failed', error: t.error };
    if (t.status === 'ready') return { status: 'ready', duration: t.duration };
    return { status: 'fetching' };
  }

  function peaksFor(key) {
    const r = rng(hash(key)), N = 700, raw = [];
    for (let i = 0; i < N; i++) raw.push(r());
    const out = [];
    for (let i = 0; i < N; i++) {
      let s = 0, n = 0;
      for (let j = i - 6; j <= i + 6; j++) if (j >= 0 && j < N) { s += raw[j]; n++; }
      const pos = i / N;
      const shape = pos < 0.06 ? pos / 0.06 : pos > 0.94 ? (1 - pos) / 0.06 : 0.55 + 0.45 * Math.abs(Math.sin(pos * Math.PI * 3.2 + (hash(key) % 7)));
      out.push(s / n * shape);
    }
    const max = Math.max(...out) || 1;
    return out.map((v) => Math.round((v / max) * 1000) / 1000);
  }

  // A quiet tone WAV as long as the track (8 kHz, 8-bit mono), loudness
  // following the peaks so what you hear lines up with the waveform.
  function toneWav(key) {
    const dur = Math.min(300, trackState(key).duration || guessDuration(key));
    const rate = 8000, n = Math.floor(dur * rate), buf = new ArrayBuffer(44 + n), v = new DataView(buf);
    const str = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
    str(0, 'RIFF'); v.setUint32(4, 36 + n, true); str(8, 'WAVE'); str(12, 'fmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate, true); v.setUint16(32, 1, true); v.setUint16(34, 8, true);
    str(36, 'data'); v.setUint32(40, n, true);
    const pk = peaksFor(key), freq = 196 + (hash(key) % 5) * 22, bytes = new Uint8Array(buf, 44);
    for (let i = 0; i < n; i++) {
      const amp = 2 + 16 * pk[Math.floor((i / n) * pk.length)];
      bytes[i] = 128 + Math.round(amp * Math.sin((2 * Math.PI * freq * i) / rate));
    }
    return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
  }

  const ytId = (url) => (url.match(/[?&]v=([\w-]{6,})/) || url.match(/youtu\.be\/([\w-]{6,})/) || [])[1] || `vid${hash(url).toString(36)}`;

  window.mockApi = {
    config: () => reply(cfg),

    ndLogin(url, username, password) {
      if (!username || password === 'wrong') return fail('Wrong username or password', { status: 401, login: true });
      cfg.nd_url = url; cfg.nd_user = username; lsSet(username);
      return reply({ user: username });
    },
    ndLogout() { cfg.nd_user = null; lsSet(null); return reply({}); },
    ndPlaylists() { return needLogin() || reply(PLAYLISTS.map(({ id, name, tracks }) => ({ id, name, count: tracks.length }))); },
    ndPlaylist(id) {
      const p = PLAYLISTS.find((x) => x.id === id);
      return needLogin() || (p ? reply(p.tracks) : fail('Playlist not found', { status: 404 }));
    },
    ndSearch(q) {
      if (!q.trim()) return reply([]);
      const list = remember(songs('q:' + q.toLowerCase(), 8, 'nd-'));
      const cap = q.trim().replace(/^./, (c) => c.toUpperCase());
      list[0].title = cap; list[2].title = `${cap} (Live)`; list[5].album = cap;
      return needLogin() || reply(list);
    },

    ytLookup(url) {
      if (!/youtu\.?be/.test(url)) return fail("That doesn't look like a YouTube link", { status: 400 });
      if (/[?&]list=/.test(url)) {
        const list = songs('yt:' + url, 6, 'yt').map((t, i) => ({ ...t, ref: `${ytId(url)}${i}`, title: `${t.artist} - ${t.title} (Official Video)`, album: '' }));
        return reply({ title: 'Mixtape Vol. 3', tracks: remember(list) });
      }
      const [t] = songs('yt:' + url, 1, 'yt');
      const one = { ...t, ref: ytId(url), title: `${t.artist} - ${t.title} (Official Audio)`, album: '' };
      return reply({ title: one.title, tracks: remember([one]) });
    },

    addTrack(source, ref) {
      if (source === 'nd' && !cfg.nd_user) return fail('Navidrome session expired', { status: 401, login: true });
      const key = `${source}:${ref}`, t = known.get(ref);
      return startFetch(key, t ? t.duration : guessDuration(key), ref === 'nd-broken' ? 'Navidrome returned 404 for this song' : undefined);
    },
    uploadTrack(file) {
      const key = `local:${hash(file.name + file.size + Date.now()).toString(36)}`, url = URL.createObjectURL(file);
      return new Promise((ok) => { // read the real duration so the uploaded file plays as itself
        const a = new Audio(); let done = false;
        const finish = (d) => { if (done) return; done = true; if (d) localAudio.set(key, url); ok(d); };
        a.onloadedmetadata = () => finish(isFinite(a.duration) ? a.duration : 0);
        a.onerror = () => finish(0);
        setTimeout(() => finish(0), 4000);
        a.src = url;
      }).then((d) => startFetch(key, d || guessDuration(key)));
    },
    track: (key) => reply(trackState(key)),
    peaks: (key) => reply(peaksFor(key)),
    audioUrl(key) {
      if (localAudio.has(key)) return localAudio.get(key);
      if (!audio.has(key)) audio.set(key, toneWav(key));
      return audio.get(key);
    },
    coverUrl: (key, which) => (which === 'custom' && covers.get(key)) || `https://picsum.photos/seed/vt${hash(key) % 1000}/300`,

    discogsSearch(q) {
      const r = rng(hash(q)), base = hash(q) % 900;
      return reply(Array.from({ length: 9 }, (_, i) => ({
        title: `${pick(r, ARTISTS)} - ${i ? pick(r, ALBUMS) : q}`,
        year: String(1975 + Math.floor(r() * 50)),
        thumb: `https://picsum.photos/seed/${base + i}/300`,
        cover: `https://picsum.photos/seed/${base + i}/600`,
        resource_url: `https://api.discogs.com/releases/${base + i}`,
      })));
    },
    discogsImages(resourceUrl) {
      const n = resourceUrl.split('/').pop(), count = 2 + (hash(n) % 5);
      return reply(Array.from({ length: count }, (_, j) => (j ? `https://picsum.photos/seed/${n}x${j}/600` : `https://picsum.photos/seed/${n}/600`)));
    },
    setCoverUrl(key, url) { covers.set(key, url); return reply({}); },
    uploadCover(key, file) { covers.set(key, URL.createObjectURL(file)); return reply({}); },

    render(payload) {
      const id = `job${++jobN}`;
      jobs.set(id, { t0: Date.now(), items: payload.items });
      return reply({ job: id });
    },
    job(id) {
      const j = jobs.get(id);
      if (!j) return fail('Unknown job', { status: 404 });
      const step = Math.floor((Date.now() - j.t0) / 1000); // one item per second
      return reply({
        items: j.items.map((it, i) => {
          const status = i < step ? 'done' : i === step ? 'rendering' : 'queued';
          if (status !== 'done') return { key: it.key, status };
          it.url ||= brokenOutputs ? `/output/${id}/missing.mp4` : URL.createObjectURL(new Blob([`mock render of ${it.name}\n`], { type: 'video/mp4' }));
          return { key: it.key, status, url: it.url };
        }),
      });
    },
  };

  // Error-path triggers for testing from the devtools console, e.g.
  //   mockDebug.expireSession()        next Navidrome call (e.g. Add all) gets 401 {login:true}
  //   mockDebug.forgetJobs()           job() returns 404 for the running render
  //   mockDebug.fail('job', 10)        next 10 job() calls fail like a network error (fail(m, n, 503) for a 5xx)
  //   mockDebug.fail('track', 5)       next 5 track() polls fail
  //   mockDebug.brokenOutputs()        finished renders point at a 404 url (prefetch fails)
  const faults = {};
  for (const [name, fn] of Object.entries(window.mockApi)) {
    if (name === 'audioUrl' || name === 'coverUrl') continue; // sync url builders
    window.mockApi[name] = (...args) => {
      const f = faults[name];
      if (f && f.n > 0) { f.n--; return fail(f.status ? `Server error ${f.status}` : 'Failed to fetch', f.status ? { status: f.status } : {}); }
      return fn(...args);
    };
  }
  window.mockDebug = {
    expireSession() { cfg.nd_user = null; lsSet(null); },
    forgetJobs() { jobs.clear(); },
    fail(method, n = 1, status = 0) { faults[method] = { n, status }; },
    brokenOutputs(on = true) { brokenOutputs = on; },
  };
})();
