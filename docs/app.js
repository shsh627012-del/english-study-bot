'use strict';

// ── 상태 ────────────────────────────────────────────────────────────────
const DATA = { expressions: [], srs: { cards: {} }, inbox: [], log: [], known: [] };
const LS = { pat: 'esa_pat', repo: 'esa_repo' };

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const todayStr = () => new Date().toLocaleDateString('sv-SE'); // YYYY-MM-DD

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
  } catch { /* 시크릿 창 등에서는 저장이 막힐 수 있다 */ }
  return null;
}

// ── 데이터 로드 ─────────────────────────────────────────────────────────
async function loadJSON(path, fallback) {
  try {
    const r = await fetch(`./data/${path}?t=${Date.now()}`);
    if (!r.ok) return fallback;
    return await r.json();
  } catch { return fallback; }
}

async function loadJSONL(path) {
  try {
    const r = await fetch(`./data/${path}?t=${Date.now()}`);
    if (!r.ok) return [];
    const text = await r.text();
    return text.trim().split('\n').filter(Boolean).map((l) => {
      try { return JSON.parse(l); } catch { return null; }
    }).filter(Boolean);
  } catch { return []; }
}

async function loadAll() {
  const [exp, srs, inbox, known, log] = await Promise.all([
    loadJSON('expressions.json', { expressions: [] }),
    loadJSON('srs.json', { cards: {} }),
    loadJSON('inbox.json', { items: [] }),
    loadJSON('known.json', { known: [] }),
    loadJSONL('log.jsonl'),
  ]);
  DATA.expressions = exp.expressions || [];
  DATA.srs = srs;
  DATA.inbox = inbox.items || [];
  DATA.known = known.known || [];
  DATA.log = log;
}

const byId = (id) => DATA.expressions.find((e) => e.id === id);

// ── 카드 렌더링 ─────────────────────────────────────────────────────────
const STATUS_KO = { pool: '대기', active: '학습 중', retired: '졸업', excluded: '제외' };
const POS_KO = {
  phrasal_verb: '구동사', idiom: '관용표현', collocation: '연어',
  noun: '명사', verb: '동사', adjective: '형용사',
};

const MT_LABEL = '(자동번역)';
const koreanOn = () => store('esa_korean') === '1';

function shortSource(src = {}) {
  const n = src.name || '';
  if (n.startsWith('Merriam-Webster')) return 'MW';
  if (n.startsWith('Wiktionary')) return 'Wiktionary';
  if (n.startsWith('Tatoeba')) return 'Tatoeba';
  if (n.startsWith('YouTube')) return 'YouTube';
  return n.split(' — ')[0] || '출처';
}

function koHTML(ko, origin) {
  if (!ko || !koreanOn()) return '';
  return `<span class="ko">${esc(ko)}${origin === 'machine' ? ` <em class="mt">${MT_LABEL}</em>` : ''}</span>`;
}

function cardHTML(e, opts = {}) {
  const p = e.pronunciation || {};
  const d = e.definition_source || {};
  const tags = [
    e.pos ? `<span class="tag grey">${esc(POS_KO[e.pos] || e.pos)}</span>` : '',
    e.status ? `<span class="tag grey">${esc(STATUS_KO[e.status] || e.status)}</span>` : '',
    d.name ? `<span class="tag">${esc(shortSource(d))}</span>` : '',
  ].join('');

  const examples = (e.examples || []).map((x) => {
    const s = x.source || {};
    const audio = x.audio?.url
      ? `<audio controls preload="none" src="${esc(x.audio.url)}" title="원어민 녹음${x.audio.author ? ' · ' + esc(x.audio.author) : ''}"></audio>`
      : '';
    return `<p><span class="en">${esc(x.en)}</span>
      <a class="src" href="${esc(s.url || '#')}" target="_blank" rel="noopener">${esc(shortSource(s))}</a>
      ${x.audio ? '<span title="원어민 녹음">🎙</span>' : ''}
      ${koHTML(x.ko, x.ko_origin)}${audio}</p>`;
  }).join('');

  const links = [
    p.youglish ? `<a href="${esc(p.youglish)}" target="_blank" rel="noopener">🔊 실제 발음</a>` : '',
    p.source_clip ? `<a href="${esc(p.source_clip)}" target="_blank" rel="noopener">📺 원본 장면</a>` : '',
    p.dict_audio ? `<a href="${esc(p.dict_audio)}" target="_blank" rel="noopener">🔤 ${esc(p.dict_word || '단어')} 발음</a>` : '',
    d.url ? `<a href="${esc(d.url)}" target="_blank" rel="noopener">📖 사전 원문</a>` : '',
    `<a href="https://en.dict.naver.com/#/search?query=${encodeURIComponent(e.text)}" target="_blank" rel="noopener">🇰🇷 네이버 사전</a>`,
    opts.promote
      ? `<button class="promote ${e.priority > 0 ? 'on' : ''}" data-id="${esc(e.id)}">
           ${e.priority > 0 ? '★ 우선 학습' : '☆ 우선 학습'}</button>`
      : '',
  ].filter(Boolean).join('');

  return `
  <article class="card" data-id="${esc(e.id)}">
    <div class="head">
      <span class="term">${esc(e.text)}</span>
      ${p.ipa ? `<span class="ipa">${esc(p.ipa)}</span>` : ''}
      ${tags}
    </div>
    <p class="meaning">${e.definition_label ? `<i class="label">[${esc(e.definition_label)}]</i> ` : ''}${esc(e.definition_en)}
      <a class="src" href="${esc(d.url || '#')}" target="_blank" rel="noopener">— ${esc(d.name || '')}</a></p>
    ${koHTML(e.meaning_ko, e.ko_origin) ? `<p class="nuance">${koHTML(e.meaning_ko, e.ko_origin)}</p>` : ''}
    <div class="ex">${examples}</div>
    ${p.tts_file ? `<audio controls preload="none" src="./${esc(p.tts_file)}" title="표현 + 예문 이어듣기"></audio>` : ''}
    <div class="links">${links}</div>
  </article>`;
}

function statHTML(items) {
  return items.map(([n, label]) => `<div class="stat"><b>${n}</b><span>${label}</span></div>`).join('');
}

// ── 오늘 ────────────────────────────────────────────────────────────────
function renderToday() {
  const today = todayStr();
  const sent = DATA.log.filter((r) => r.date === today && r.event === 'sent');
  const sentNew = sent.filter((r) => r.kind === 'new');
  const graded = DATA.log.filter((r) => r.date === today && r.event === 'graded');

  const due = Object.entries(DATA.srs.cards || {})
    .filter(([, c]) => (c.due || '') <= today)
    .map(([id]) => byId(id)).filter(Boolean);

  $('#today-stats').innerHTML = statHTML([
    [sentNew.length, '오늘 새 표현'],
    [due.length, '복습 예정'],
    [graded.length, '오늘 응답'],
    [DATA.expressions.filter((e) => e.status === 'pool').length, '대기 중인 표현'],
  ]);

  const cards = sentNew.map((r) => byId(r.id)).filter(Boolean);
  $('#today-cards').innerHTML = cards.length
    ? cards.map((e) => cardHTML(e)).join('')
    : '<p class="muted">아직 오늘 보낸 표현이 없습니다.</p>';

  $('#today-due').innerHTML = due.length
    ? due.map((e) => cardHTML(e)).join('')
    : '<p class="muted">오늘 복습할 표현이 없습니다. 👏</p>';
}

// ── 아카이브 ────────────────────────────────────────────────────────────
function renderArchive() {
  const q = $('#q').value.trim().toLowerCase();
  const src = $('#f-source').value;
  const def = $('#f-def').value;
  const st = $('#f-status').value;

  const hits = DATA.expressions.filter((e) => {
    if (src && e.source?.type !== src) return false;
    if (def && shortSource(e.definition_source) !== def) return false;
    if (st && e.status !== st) return false;
    if (!q) return true;
    const hay = [e.text, e.definition_en, e.meaning_ko,
      ...(e.examples || []).flatMap((x) => [x.en, x.ko])].join(' ').toLowerCase();
    return hay.includes(q);
  }).slice().reverse();

  $('#archive-count').textContent =
    `${hits.length}개 / 전체 ${DATA.expressions.length}개`;
  $('#archive-cards').innerHTML = hits.length
    ? hits.map((e) => cardHTML(e, { promote: true })).join('')
    : '<p class="muted">조건에 맞는 표현이 없습니다.</p>';
}

// ── 진도 ────────────────────────────────────────────────────────────────
const BOX_DAYS = { 1: 1, 2: 3, 3: 7, 4: 16, 5: 35 };

function renderProgress() {
  const cards = Object.values(DATA.srs.cards || {});
  const dist = {};
  cards.forEach((c) => { if (c.box <= 5) dist[c.box] = (dist[c.box] || 0) + 1; });
  const max = Math.max(1, ...Object.values(dist));

  const graded = DATA.log.filter((r) => r.event === 'graded');
  const know = graded.filter((r) => r.grade === 'know' || r.grade === 'too_easy').length;

  $('#progress-stats').innerHTML = statHTML([
    [DATA.expressions.filter((e) => e.status === 'active').length, '학습 중'],
    [DATA.expressions.filter((e) => e.status === 'retired').length, '졸업'],
    [graded.length ? `${Math.round(know / graded.length * 100)}%` : '–', '아는 비율'],
    [DATA.known.length, '너무 쉬움 처리'],
  ]);

  $('#boxes').innerHTML = [1, 2, 3, 4, 5].map((b) => {
    const n = dist[b] || 0;
    return `<div class="boxrow">
      <span class="label">박스 ${b} · ${BOX_DAYS[b]}일</span>
      <span class="bar" style="width:${Math.round(n / max * 68)}%"></span>
      <span>${n}</span></div>`;
  }).join('');

  // 최근 14일 학습량
  const days = [...Array(14)].map((_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (13 - i));
    return d.toLocaleDateString('sv-SE');
  });
  const counts = days.map((d) =>
    DATA.log.filter((r) => r.date === d && r.event === 'sent' && r.kind === 'new').length);
  const top = Math.max(1, ...counts);
  $('#activity').innerHTML = days.map((d, i) => `
    <div class="${counts[i] ? 'has' : ''}" style="height:${Math.max(3, counts[i] / top * 100)}%"
         title="${d} · ${counts[i]}개"><span>${d.slice(8)}</span></div>`).join('');

  const trouble = {};
  graded.filter((r) => r.grade === 'unknown' || r.grade === 'vague')
    .forEach((r) => { trouble[r.text] = (trouble[r.text] || 0) + 1; });
  const list = Object.entries(trouble).sort((a, b) => b[1] - a[1]).slice(0, 5);
  $('#trouble').innerHTML = list.length
    ? list.map(([t, n]) => `<li>${esc(t)} <span class="muted">(${n}회)</span></li>`).join('')
    : '<p class="muted">아직 데이터가 없습니다.</p>';
}

// ── 대기열 ──────────────────────────────────────────────────────────────
const STATUS_LABEL = { pending: '처리 대기', processed: '완료', failed: '실패' };

function renderInbox() {
  $('#inbox-list').innerHTML = DATA.inbox.length
    ? DATA.inbox.slice().reverse().map((i) => {
        const names = (i.extracted || []).map((id) => byId(id)?.text).filter(Boolean);
        return `<div class="inbox-item">
          <span class="status ${esc(i.status)}">${esc(STATUS_LABEL[i.status] || i.status)}</span>
          <div class="url">${esc(i.url)}</div>
          <div class="meta">
            ${esc((i.added_at || '').slice(0, 16).replace('T', ' '))} · ${esc(i.added_by || '')}
            ${names.length ? `<br>추출: ${names.map(esc).join(', ')}` : ''}
            ${i.error ? `<br>⚠ ${esc(i.error)}` : ''}
          </div></div>`;
      }).join('')
    : '<p class="muted">대기열이 비어 있습니다.</p>';
}

// ── GitHub 쓰기 (fine-grained PAT, 브라우저에만 저장) ───────────────────
const b64encode = (s) => btoa(String.fromCharCode(...new TextEncoder().encode(s)));
const b64decode = (s) => new TextDecoder().decode(
  Uint8Array.from(atob(s.replace(/\s/g, '')), (c) => c.charCodeAt(0)));

function creds() {
  const pat = store(LS.pat);
  const repo = store(LS.repo);
  if (!pat || !repo) throw new Error('설정 탭에서 리포와 토큰을 먼저 입력하세요.');
  return { pat, repo };
}

async function ghFetch(path, init = {}) {
  const { pat, repo } = creds();
  const r = await fetch(`https://api.github.com/repos/${repo}/contents/${path}`, {
    ...init,
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${pat}`,
      'X-GitHub-Api-Version': '2022-11-28',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...init.headers,
    },
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    if (r.status === 401) throw new Error('토큰이 거부됐습니다. 만료됐거나 권한이 부족합니다.');
    if (r.status === 404) throw new Error('리포나 파일을 찾을 수 없습니다. 리포 이름과 토큰 권한을 확인하세요.');
    if (r.status === 409) throw new Error('다른 곳에서 먼저 수정됐습니다. 새로고침 후 다시 시도하세요.');
    throw new Error(detail.message || `GitHub 오류 ${r.status}`);
  }
  return r.json();
}

async function ghWriteJSON(path, transform, message) {
  const current = await ghFetch(path);
  const data = JSON.parse(b64decode(current.content));
  const next = transform(data);
  if (!next) return null;                        // 변경 없음
  await ghFetch(path, {
    method: 'PUT',
    body: JSON.stringify({
      message,
      content: b64encode(JSON.stringify(next, null, 2) + '\n'),
      sha: current.sha,
    }),
  });
  return next;
}

// ── 링크 투입 ───────────────────────────────────────────────────────────
async function addUrl() {
  const input = $('#new-url');
  const msg = $('#inbox-msg');
  const url = input.value.trim();
  if (!url) return;

  const btn = $('#add-url');
  btn.disabled = true;
  msg.textContent = '추가하는 중…';
  try {
    const next = await ghWriteJSON('docs/data/inbox.json', (data) => {
      const items = data.items || [];
      if (items.some((i) => i.url === url)) return null;
      items.push({
        id: `in_${String(items.length + 1).padStart(4, '0')}`,
        url,
        added_by: 'web',
        added_at: new Date().toISOString().replace(/\.\d+Z$/, '+00:00'),
        status: 'pending',
        extracted: [],
        error: null,
      });
      return { items };
    }, `웹에서 링크 추가: ${url.slice(0, 60)}`);

    if (!next) {
      msg.textContent = '이미 대기열에 있는 링크입니다.';
    } else {
      DATA.inbox = next.items;
      input.value = '';
      msg.textContent = '대기열에 담았습니다. PC 에서 수집 스크립트를 돌리면 표현이 추출됩니다.';
      renderInbox();
    }
  } catch (e) {
    msg.textContent = `⚠ ${e.message}`;
  }
  btn.disabled = false;
}

// ── 우선 학습 승격 ──────────────────────────────────────────────────────
async function togglePromote(id, button) {
  const exp = byId(id);
  if (!exp) return;
  const want = exp.priority > 0 ? 0 : 1;

  button.disabled = true;
  const before = button.textContent;
  button.textContent = '…';
  try {
    await ghWriteJSON('docs/data/expressions.json', (data) => {
      const target = (data.expressions || []).find((e) => e.id === id);
      if (!target) return null;
      target.priority = want;
      return data;
    }, `${want ? '우선 학습 지정' : '우선 학습 해제'}: ${exp.text}`);

    exp.priority = want;
    button.classList.toggle('on', want > 0);
    button.textContent = want > 0 ? '★ 우선 학습' : '☆ 우선 학습';
  } catch (e) {
    button.textContent = before;
    alert(e.message);
  }
  button.disabled = false;
}

// ── 설정 ────────────────────────────────────────────────────────────────
function renderSettings() {
  $('#repo').value = store(LS.repo) || '';
  $('#pat').value = store(LS.pat) ? '••••••••••••••••' : '';
  $('#pat-msg').textContent = store(LS.pat) ? '토큰이 이 브라우저에 저장되어 있습니다.' : '';
}

function savePat() {
  const repo = $('#repo').value.trim().replace(/^https?:\/\/github\.com\//, '').replace(/\/$/, '');
  const pat = $('#pat').value.trim();
  if (!repo.includes('/')) { $('#pat-msg').textContent = '⚠ 리포는 사용자명/리포명 형식입니다.'; return; }
  store(LS.repo, repo);
  if (pat && !pat.startsWith('•')) store(LS.pat, pat);
  $('#pat').value = store(LS.pat) ? '••••••••••••••••' : '';
  $('#pat-msg').textContent = '저장했습니다.';
}

function clearPat() {
  store(LS.pat, null);
  store(LS.repo, null);
  $('#repo').value = '';
  $('#pat').value = '';
  $('#pat-msg').textContent = '지웠습니다.';
}

// ── 초기화 ──────────────────────────────────────────────────────────────
function wire() {
  $$('#tabs button').forEach((b) => b.addEventListener('click', () => {
    $$('#tabs button').forEach((x) => x.classList.toggle('active', x === b));
    $$('.panel').forEach((p) => p.classList.toggle('active', p.id === b.dataset.tab));
  }));

  ['#q', '#f-source', '#f-def', '#f-status'].forEach((s) => {
    $(s).addEventListener('input', renderArchive);
  });

  $('#korean').checked = koreanOn();
  $('#korean').addEventListener('change', (e) => {
    store('esa_korean', e.target.checked ? '1' : null);
    renderToday(); renderArchive();
  });

  $('#add-url').addEventListener('click', addUrl);
  $('#new-url').addEventListener('keydown', (e) => { if (e.key === 'Enter') addUrl(); });
  $('#save-pat').addEventListener('click', savePat);
  $('#clear-pat').addEventListener('click', clearPat);

  // 승격 버튼은 카드가 다시 그려지므로 위임으로 잡는다.
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('button.promote');
    if (btn) togglePromote(btn.dataset.id, btn);
  });
}

function renderHeadline() {
  const total = DATA.expressions.length;
  const active = DATA.expressions.filter((e) => e.status === 'active').length;
  const retired = DATA.expressions.filter((e) => e.status === 'retired').length;
  $('#headline').textContent = total
    ? `표현 ${total}개 · 학습 중 ${active} · 졸업 ${retired}`
    : '아직 표현이 없습니다. python -m src.seed 로 시작하세요.';

  const last = DATA.log[DATA.log.length - 1];
  $('#updated').textContent = last
    ? `마지막 기록: ${last.at.slice(0, 16).replace('T', ' ')} UTC`
    : '';
}

(async function init() {
  wire();
  renderSettings();
  await loadAll();
  renderHeadline();
  renderToday();
  renderArchive();
  renderProgress();
  renderInbox();
})();
