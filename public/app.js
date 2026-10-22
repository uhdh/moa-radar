'use strict';
import {publication,compareNewest} from './post-time.mjs';
import {exactMatch,matchesExact} from './keyword-match.mjs';

const $ = id => document.getElementById(id);
const staticMode = document.documentElement.dataset.mode === 'static';
const cloudMode = document.documentElement.dataset.mode === 'cloud';
const apiBase = cloudMode ? document.documentElement.dataset.api : '';
let workspaceKey = '';
let snapshot;
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const SOURCE_DEFAULTS = {
  dc: {name:'디시인사이드',color:'#6c8cff',short:'dc',domain:'dcinside.com'},
  clien: {name:'클리앙',color:'#61b5ca',short:'cl',domain:'clien.net'},
  ruliweb: {name:'루리웹',color:'#a999ec',short:'ru',domain:'ruliweb.com'},
  fmkorea: {name:'에펨코리아',color:'#e6ad5c',short:'fm',domain:'fmkorea.com'}
};
let sources = SOURCE_DEFAULTS;
let storageError = false;
function readStorage(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
  catch { storageError = true; return fallback; }
}
function saveStorage(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); }
  catch { storageError = true; toast('이 브라우저에서는 저장할 수 없어요. 현재 화면에서만 유지됩니다.'); }
}
const staticExact = Object.assign(Object.create(null),readStorage('moa.staticExact', {}));
const topicSettings = rows => rows.map(topic => ({...topic,exact:typeof staticExact[topic.keyword] === 'boolean' ? staticExact[topic.keyword] : topic.exact}));
const apiHeaders = extra => cloudMode ? {...extra,Authorization:'Bearer ' + workspaceKey} : extra;
async function readData(resource, signal) {
  if (staticMode) {
    if (!snapshot || resource.startsWith('search?')) {
      const response = await fetch('./snapshot.json?t=' + Date.now(), {signal,cache:'no-store'});
      if (!response.ok) throw new Error('수집 결과를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.');
      snapshot = await response.json();
      if (snapshot.schema !== 1 || !Array.isArray(snapshot.topics) || !snapshot.feeds || !snapshot.sources) throw new Error('수집 결과 형식이 올바르지 않습니다.');
    }
    if (resource === 'sources') return snapshot.sources;
    if (resource === 'topics') return {topics:topicSettings(snapshot.topics)};
    topics = topicSettings(snapshot.topics);
    const keyword = new URLSearchParams(resource.split('?')[1]).get('q');
    if (!Object.hasOwn(snapshot.feeds,keyword)) throw new Error('아직 등록되지 않은 키워드입니다. 왼쪽의 수집 키워드 설정에서 등록하고 GitHub에 저장해 주세요.');
    return snapshot.feeds[keyword];
  }
  const response = await fetch(apiBase + '/api/' + resource,{signal,headers:resource === 'sources' ? {} : apiHeaders({})});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '요청에 실패했습니다.');
  return result;
}
function configureTopics() {
  if (!snapshot || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(snapshot.repository)) return toast('설정 주소를 읽지 못했습니다. 새로고침해 주세요.');
  window.open(`https://github.com/${snapshot.repository}/edit/main/keywords.json`,'_blank','noopener,noreferrer');
}
function safeUrl(value, source) {
  try {
    const url = new URL(value);
    const meta = sources[source];
    const domains = meta ? [meta.domain,...(meta.domains || [])] : [];
    return ['https:','http:'].includes(url.protocol) && !url.username && !url.password && domains.some(domain => url.hostname === domain || url.hostname.endsWith('.' + domain)) ? url.href : '';
  } catch { return ''; }
}
function safeSearchUrl(value, source) {
  const sourceUrl = safeUrl(value, source);
  if (sourceUrl) return sourceUrl;
  try {
    const url = new URL(value);
    return ['blog','cafe'].includes(source) && url.protocol === 'https:' && url.hostname === 'search.naver.com' && url.pathname === '/search.naver' && !url.username && !url.password ? url.href : '';
  } catch { return ''; }
}
function validPost(post) {
  return post && typeof post.title === 'string' && !!sources[post.source] && !!safeUrl(post.url, post.source);
}
function datedPost(post, observedAt='') {
  const dated = {...post,id:post.url,observedAt:post.observedAt || observedAt};
  return {...dated,dateInfo:publication(dated)};
}
const storedTopics = readStorage('moa.topics', []);
let topics = (Array.isArray(storedTopics) ? storedTopics : []).filter(t => t && typeof t.keyword === 'string' && t.keyword.trim() && t.keyword.length <= 80).map(t => ({keyword:t.keyword,exclude:Array.isArray(t.exclude) ? t.exclude.filter(x => typeof x === 'string') : [],exact:t.exact === true})).slice(0,30);
const storedBookmarks = readStorage('moa.bookmarks', []);
let bookmarks = [], unavailableBookmarks = [];
let posts = [], connections = [], currentKeyword = '', activeTab = 'all', savedView = false, loading = false, searchedAt = '', searchError = '', controller, toastTimer, searchSequence = 0;
let dailyInfo = null, pollTimer, topicsReady = false;
let exactMode = false, exactSaving = false, exactDefault = readStorage('moa.exact',false) === true;
const selected = new Set(Object.keys(sources));
let initialized = false;
const format = n => Number(n).toLocaleString('ko-KR');
const dateKey = value => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : new Date(date.getTime() + 9 * 3600000).toISOString().slice(0,10);
};
const dateTime = value => {
  if (!value) return '게시일 미확인';
  const thisYear = dateKey(new Date()).slice(0,4);
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value.slice(0,4) === thisYear ? '' : value.slice(0,4) + '.'}${value.slice(5,7)}.${value.slice(8,10)}`;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '게시일 미확인';
  const parts = Object.fromEntries(new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date).map(part => [part.type,part.value]));
  return `${parts.year === thisYear ? '' : parts.year + '.'}${parts.month}.${parts.day} ${parts.hour}:${parts.minute}`;
};
function toast(message) {
  clearTimeout(toastTimer); $('toast').textContent = message; $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3200);
}
function highlighted(value) {
  const text = String(value ?? '').normalize('NFC');
  if (savedView || !currentKeyword) return escapeHtml(text);
  const match = exactMode ? exactMatch(text,currentKeyword) : null;
  const index = exactMode ? (match?.index ?? -1) : text.toLocaleLowerCase().indexOf(currentKeyword.toLocaleLowerCase());
  const length = exactMode ? (match?.value.length ?? 0) : currentKeyword.length;
  return index < 0 ? escapeHtml(text) : escapeHtml(text.slice(0,index)) + '<mark>' + escapeHtml(text.slice(index,index + length)) + '</mark>' + escapeHtml(text.slice(index + length));
}
function excluded(post) {
  if (savedView) return false;
  const topic = topics.find(t => t.keyword === currentKeyword);
  const content = `${post.title} ${post.snippet ?? ''}`.toLocaleLowerCase();
  return topic?.exclude.some(word => content.includes(word.toLocaleLowerCase())) ?? false;
}
function basePosts() {
  const within = $('within').value.trim().toLocaleLowerCase();
  const period = $('period').value;
  const cutoff = period === 'all' ? null : Date.now() - Number(period) * 86400000;
  return (savedView ? bookmarks : posts).filter(p => {
    const publishedTime = p.dateInfo.time;
    return selected.has(p.source) && !excluded(p) && (savedView || !exactMode || matchesExact(p,currentKeyword)) && (!within || `${p.title} ${p.snippet ?? ''}`.toLocaleLowerCase().includes(within)) && (cutoff === null || (publishedTime !== null && publishedTime >= cutoff && publishedTime <= Date.now() && (period !== '1' || !p.dateInfo.dayOnly)));
  });
}
function filteredPosts() {
  return basePosts().filter(p => activeTab === 'all' || p.source === activeTab).sort((a,b) => $('sort').value === 'comments' ? ((b.comments ?? -1) - (a.comments ?? -1)) || compareNewest(a,b) : compareNewest(a,b));
}
function renderTopics() {
  $('topics').innerHTML = topics.length ? topics.map((topic,index) => `<div class="topic-row ${!savedView && currentKeyword === topic.keyword ? 'active' : ''}"><button class="topic-button" data-topic="${index}" title="${escapeHtml(topic.keyword)}${topic.exact ? ' · 정확한 단어만' : ''}${topic.exclude.length ? ' · 제외: ' + escapeHtml(topic.exclude.join(', ')) : ''}"><span class="topic-hash">#</span><span class="topic-name">${escapeHtml(topic.keyword)}</span></button>${staticMode ? '' : `<button class="topic-delete" data-delete="${index}" aria-label="${escapeHtml(topic.keyword)} 관심 키워드 삭제">×</button>`}</div>`).join('') : '<span class="topic-empty">자주 찾는 키워드를 담아보세요.</span>';
}
async function updateTopic(data) {
  const response = await fetch(apiBase + '/api/topics', {method:'POST',headers:apiHeaders({'Content-Type':'application/json'}),body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '키워드를 저장하지 못했습니다.');
  if (!Array.isArray(result.topics)) throw new Error('키워드 목록을 읽지 못했습니다.');
  topics = result.topics;
  saveStorage('moa.topics',topics);
}
async function persistExact(keyword, exact) {
  const topic = topics.find(t => t.keyword === keyword);
  if (!topic || (topic.exact === true) === exact) return;
  if (staticMode) {staticExact[keyword]=exact;topic.exact=exact;saveStorage('moa.staticExact',staticExact);return;}
  if (!topicsReady) throw new Error('서버의 키워드 목록을 먼저 불러와야 합니다. 새로고침해 주세요.');
  await updateTopic({...topic,exact});
}
async function setExactMode(exact) {
  const previous = exactMode;
  exactMode = exact; $('exact-match').checked = exact; exactSaving = true; render();
  try {await persistExact(currentKeyword,exact);exactDefault=exact;saveStorage('moa.exact',exact);}
  catch(error){exactMode=previous;$('exact-match').checked=previous;toast(error.message);}
  finally{exactSaving=false;render();}
}
function renderSourceControls() {
  const groups = [['naver','네이버'],['community','커뮤니티'],['social','SNS']];
  $('source-controls').innerHTML = groups.map(([group,label]) => {
    const rows = Object.entries(sources).filter(([,s]) => (s.group || 'community') === group);
    return rows.length ? `<div class="source-group-label">${label}<span>${rows.length}</span></div>` + rows.map(([key,s]) => `<label class="source-control" style="--source-color:${s.color}" title="${escapeHtml(s.scope || s.name)}"><span class="source-icon">${escapeHtml(s.short)}</span>${escapeHtml(s.name)}<input type="checkbox" data-source="${key}" ${selected.has(key) ? 'checked' : ''} aria-label="${escapeHtml(s.name)} 결과 포함"></label>`).join('') : '';
  }).join('');
  $('source-selected').textContent = `${selected.size} / ${Object.keys(sources).length}`;
  $('sources-total').textContent = `/ ${Object.keys(sources).length}`;
  $('search-scope').textContent = `${Object.keys(sources).length}개 소스 · 커뮤니티·SNS 공개 검색`;
}
function renderStats(data) {
  $('total-stat').textContent = loading && !posts.length ? '—' : format(data.length);
  $('total-note').textContent = savedView ? '저장한 글 중 현재 필터에 맞는 이야기' : (currentKeyword ? `‘${currentKeyword}’ 검색 · 현재 필터 기준` : '키워드를 검색하면 여기에 모여요');
  const now = Date.now();
  $('today-stat').textContent = loading && !posts.length ? '—' : format(data.filter(p => p.dateInfo.time !== null && !p.dateInfo.dayOnly && now - p.dateInfo.time >= 0 && now - p.dateInfo.time <= 86400000).length);
  $('sources-stat').textContent = loading ? '…' : format(connections.filter(c => c.status === 'ok').length);
  const errors = connections.filter(c => c.status !== 'ok').length;
  const native = connections.filter(c => c.status === 'ok' && c.method !== 'indexed').length;
  const indexed = connections.filter(c => c.status === 'ok' && c.method === 'indexed').length;
  $('sources-note').textContent = loading ? '커뮤니티·SNS에서 검색하고 있어요' : connections.length ? `직접 ${native} · 공개 웹 ${indexed}${errors ? ` · 확인 필요 ${errors}` : ''}` : '소스별 검색 상태 확인';
  $('bookmarks-stat').textContent = format(bookmarks.length);
  $('saved-count').textContent = format(bookmarks.length);
  $('nav-count').textContent = currentKeyword ? format(posts.length) : '—';
}
function renderTabs(data) {
  const counts = Object.fromEntries(Object.keys(sources).map(source => [source,data.filter(p => p.source === source).length]));
  $('feed-tabs').innerHTML = `<button data-tab="all" class="${activeTab === 'all' ? 'active' : ''}" aria-pressed="${activeTab === 'all'}">전체 <span class="tab-count">${format(data.length)}</span></button>` + Object.entries(sources).map(([key,s]) => `<button data-tab="${key}" class="${activeTab === key ? 'active' : ''}" ${selected.has(key) ? '' : 'disabled'} aria-pressed="${activeTab === key}">${escapeHtml(s.name)}<span class="tab-count">${format(counts[key])}</span></button>`).join('');
}
function renderInsights(data) {
  const counts = Object.entries(sources).map(([key,s]) => ({...s,key,count:data.filter(p => p.source === key).length}));
  $('donut-total').textContent = format(data.length);
  let angle = 0;
  const segments = counts.filter(s => s.count).map(s => { const start = angle; angle += s.count / data.length * 360; return `${s.color} ${start}deg ${angle}deg`; });
  $('donut').style.background = segments.length ? `conic-gradient(${segments.join(',')})` : '#30353a';
  $('source-breakdown').innerHTML = counts.map(s => `<div class="breakdown-row" style="--source-color:${s.color}"><i></i><span>${escapeHtml(s.name)}</span><span class="bar-track"><span style="width:${data.length ? s.count / data.length * 100 : 0}%"></span></span><b>${format(s.count)}</b><small>${data.length ? Math.round(s.count / data.length * 100) : 0}%</small></div>`).join('');
  const today = new Date(dateKey(new Date()) + 'T00:00:00+09:00');
  const days = Array.from({length:7},(_,i) => {const key=dateKey(new Date(today.getTime() - (6-i)*86400000));return {key,count:data.filter(p => p.dateInfo.time !== null && dateKey(p.dateInfo.time) === key).length};});
  $('week-total').textContent = format(days.reduce((sum,d) => sum+d.count,0));
  const max = Math.max(1,...days.map(d => d.count));
  $('trend-chart').innerHTML = days.map(d => `<div class="chart-col" title="${d.key}: ${d.count}건"><span class="chart-count">${d.count || ''}</span><span class="chart-bar" style="height:${Math.max(2,d.count / max * 75)}%"></span><span class="chart-label">${Number(d.key.slice(5,7))}.${Number(d.key.slice(8))}</span></div>`).join('');
  $('connection-status').innerHTML = Object.entries(sources).map(([key,s]) => {
    const connection = connections.find(c => c.source === key);
    const status = loading ? 'waiting' : connection?.status === 'ok' ? 'ok' : connection ? 'error' : 'waiting';
    const count = posts.filter(p => p.source === key).length;
    const label = loading ? '검색 중' : connection?.status === 'ok' ? `${connection.method === 'indexed' ? '공개 웹 검색' : '직접 검색'} · ${count}` : connection ? '확인 필요' : '대기';
    const url = connection && safeSearchUrl(connection.searchUrl,key);
    return `<div class="connection-item"><div class="connection-row" title="${escapeHtml(s.scope || s.name)}">${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.name)} ↗</a>` : `<span>${escapeHtml(s.name)}</span>`}<span class="status-label ${status}"><i class="status-indicator"></i>${label}</span></div>${!loading && connection?.message ? `<p class="connection-note">${escapeHtml(connection.message)}</p>` : ''}</div>`;
  }).join('');
}
function renderFeed(data) {
  $('feed-title').innerHTML = `${savedView ? '저장한 이야기' : '모든 이야기'} <span id="result-count">${format(data.length)}</span>`;
  $('feed').setAttribute('aria-busy',String(loading && !savedView));
  if (loading && !savedView) {
    $('feed').innerHTML = '<div class="loading-state"><p><i class="spinner"></i>커뮤니티·SNS에서 이야기를 모으고 있어요…</p>' + Array.from({length:4},() => '<div class="skeleton"><span></span><span></span><span></span><span></span></div>').join('') + '</div>';
    return;
  }
  if (!data.length) {
    if ((staticMode || cloudMode) && !savedView && !topics.length && !searchError) {
      $('feed').innerHTML = `<div class="empty-state"><span class="empty-symbol">＋</span><h3>수집할 키워드를 등록해 주세요</h3><p>${cloudMode ? '위 검색창에 키워드를 입력하거나 키워드 추가를 눌러 주세요.<br>등록 즉시 첫 수집을 시작하고, 이후 하루 한 번 갱신합니다.' : '왼쪽의 수집 키워드 설정을 눌러 GitHub에서 저장하세요.<br>첫 수집 후 결과가 표시됩니다. 이후 매일 오전 9시(한국시간)에 갱신됩니다.'}</p></div>`;
      return;
    }
    if (!savedView && dailyInfo && ['pending','running'].includes(dailyInfo.status)) {
      $('feed').innerHTML = '<div class="empty-state"><span class="empty-symbol">◷</span><h3>첫 수집 결과를 준비하고 있어요</h3><p>완료되면 자동으로 표시됩니다.<br>다른 키워드가 수집 중이면 차례를 기다릴 수 있어요.</p></div>';
      return;
    }
    const hasFilters = $('within').value || $('period').value !== 'all' || activeTab !== 'all' || selected.size < Object.keys(sources).length || (!savedView && exactMode);
    $('feed').innerHTML = `<div class="empty-state"><span class="empty-symbol">⌕</span><h3>${savedView ? '아직 담긴 이야기가 없어요' : hasFilters ? '조건에 맞는 이야기가 없어요' : '찾은 이야기가 없어요'}</h3><p>${savedView ? '글 오른쪽의 저장 버튼을 눌러<br>다시 읽고 싶은 이야기를 담아두세요.' : hasFilters ? '검색 결과 필터나 기간을 바꿔보세요.' : '다른 키워드로 검색해 보세요.<br>사이트의 응답 상태도 확인해 주세요.'}</p>${hasFilters ? '<button class="button secondary" id="reset-filters">결과 필터 초기화</button>' : ''}</div>`;
    return;
  }
  const bookmarked = new Set(bookmarks.map(p => p.url));
  $('feed').innerHTML = data.map((post,index) => {
    const s = sources[post.source];
    const saved = bookmarked.has(post.url);
    const url = escapeHtml(safeUrl(post.url,post.source));
    const info = post.dateInfo;
    const date = info.time === null ? (post.publishedText || '게시일 미확인') : dateTime(post.published || (info.dayOnly ? dateKey(info.time) : new Date(info.time).toISOString())) + (info.approximate ? ' · 추정' : '');
    const tooltip = info.time === null ? '게시일을 확인할 수 없어 최신순 목록의 아래에 표시합니다.' : info.approximate ? `원문 ${post.publishedText} · 수집 시각 ${dateTime(post.observedAt)} 기준 추정` : info.dayOnly ? '날짜만 제공된 글입니다. 같은 날의 시각이 있는 글 다음에 표시합니다.' : '게시 시각';
    const divider = $('sort').value === 'latest' && info.time === null && (index === 0 || data[index-1].dateInfo.time !== null) ? '<div class="date-divider">게시일 미확인 · 아래 글은 최신순 정렬에서 제외됩니다.</div>' : '';
    return `${divider}<article class="post" style="--source-color:${s.color}"><div class="post-meta"><span class="source-tag"><i></i>${escapeHtml(s.name)}</span>${post.board ? `<span class="post-board">${escapeHtml(post.board)}</span>` : ''}<time class="post-time" title="${escapeHtml(tooltip)}" ${info.time !== null ? `datetime="${new Date(info.time).toISOString()}"` : ''}>${escapeHtml(date)}</time></div><button class="bookmark" data-bookmark="${escapeHtml(post.url)}" aria-label="${saved ? '저장 취소' : '글 저장'}: ${escapeHtml(post.title)}" aria-pressed="${saved}" title="${saved ? '저장 취소' : '글 저장'}">${saved ? '◆' : '♧'}</button><a class="post-title" href="${url}" target="_blank" rel="noopener noreferrer">${highlighted(post.title)}</a>${post.snippet ? `<p class="post-snippet">${highlighted(post.snippet)}</p>` : ''}<div class="post-bottom">${post.discovery === 'indexed' ? '<span class="discovery-tag">공개 웹 검색</span>' : ''}${Number.isFinite(post.comments) ? `<span>댓글 <b>${format(post.comments)}</b></span>` : '<span>댓글 미제공</span>'}${Number.isFinite(post.views) ? `<span>조회 <b>${format(post.views)}</b></span>` : ''}<a class="post-origin" href="${url}" target="_blank" rel="noopener noreferrer">원문 보기 ↗</a></div></article>`;
  }).join('');
}
function render() {
  const base = basePosts();
  const data = filteredPosts();
  document.querySelectorAll('[data-source-shortcut]').forEach(button => {
    button.disabled = !initialized || !sources[button.dataset.sourceShortcut];
    button.setAttribute('aria-pressed', String(!savedView && activeTab === button.dataset.sourceShortcut));
  });
  $('feed-nav').classList.toggle('active',!savedView);
  $('saved-nav').classList.toggle('active',savedView);
  $('page-name').textContent = savedView ? '저장한 글' : '전체 피드';
  $('search-button').disabled = loading || exactSaving;
  $('refresh').disabled = loading || exactSaving;
  $('exact-match').disabled = !initialized || savedView || exactSaving;
  $('refresh').title = staticMode || cloudMode || dailyInfo ? '저장된 결과 새로고침 · 추가 수집 없음' : '다시 검색 (5분 캐시)';
  $('daily-collection').hidden = savedView || !dailyInfo;
  if (dailyInfo) {
    const state = {pending:'첫 수집 대기',running:'수집 중',complete:'수집 완료',error:'수집 실패',interrupted:'수집 중단'}[dailyInfo.status] || '';
    $('daily-collection').textContent = `하루 1회 · ${state}${dailyInfo.collectedAt ? ' · 최근 ' + dateTime(dailyInfo.collectedAt) : ''} · 다음 ${dateTime(dailyInfo.nextRunAt)} (한국시간)`;
  }
  $('export').disabled = !data.length || (loading && !savedView);
  const notes = [];
  if (staticMode) notes.push('하루 1회 수집한 등록 키워드의 결과입니다. 정확한 단어 체크와 글 저장은 이 브라우저에 보관됩니다.');
  if (cloudMode && !currentKeyword) notes.push('처음 등록하면 바로 수집합니다. 등록 목록은 이 브라우저에 연결되며, 이후 매일 오전 9시(한국시간)부터 하루 한 번 갱신됩니다.');
  if (dailyInfo?.message) notes.push(dailyInfo.message);
  if (dailyInfo?.collectedAt) notes.push('저장된 수집 결과입니다. 새로고침해도 추가로 수집하지 않습니다.');
  if (exactMode && !savedView) notes.push('정확한 단어만: 제목·요약에서 띄어쓰기·문장부호로 구분된 단어를 찾습니다. 붙은 조사·다른 단어는 제외합니다.');
  if (searchError) notes.push(searchError);
  else if (searchedAt) {
    const errors = connections.filter(c => c.status !== 'ok');
    const topic = topics.find(t => t.keyword === currentKeyword);
    if (errors.length) notes.push(`${errors.length}개 소스의 결과를 확인하지 못했어요. 검색 연결 상태에서 직접 검색할 수 있습니다.`);
    if (topic?.exclude.length) notes.push(`제외 단어 적용: ${topic.exclude.join(', ')}`);
    const indexed = connections.filter(c => c.method === 'indexed' && c.status === 'ok').length;
    if (indexed) notes.push(`${indexed}개 소스는 공개 웹 검색으로 찾았어요. 검색 색인 지연·누락이 있습니다.`);
    if (connections.some(c => c.message && c.status === 'ok')) notes.push('직접 검색의 범위·제한은 연결 상태의 소스별 설명을 확인해 주세요.');
  }
  if ($('sort').value === 'latest' && data.length) notes.push('최신순은 확인·추정 게시 시각 기준입니다. 상대시간은 수집 시각에 맞춰 계산하고, 게시일 미확인 글은 맨 아래에 표시합니다.');
  $('notice').textContent = notes.join(' ');
  $('notice').hidden = loading || savedView || !notes.length;
  renderTopics(); renderStats(base); renderTabs(base); renderInsights(base); renderFeed(data);
}
async function search(keyword, polling=false, exactOverride) {
  if (!initialized) return;
  keyword = keyword.trim();
  if (!keyword || keyword.length > 80) return toast('검색어는 1~80자로 입력해 주세요.');
  controller?.abort();
  clearTimeout(pollTimer);
  controller = new AbortController();
  const sequence = ++searchSequence;
  savedView = false; currentKeyword = keyword; loading = !polling || !posts.length;
  if (!polling) {
    const topic = topics.find(t => t.keyword === keyword);
    exactMode = exactOverride ?? (topic ? topic.exact === true : exactDefault);
    $('exact-match').checked = exactMode;
    activeTab = 'all'; posts = []; connections = []; searchedAt = ''; dailyInfo = null;
    $('within').value = ''; $('period').value = 'all';
  }
  searchError = ''; $('keyword').value = keyword;
  $('last-updated').textContent = '검색 중'; $('notice').hidden = true;
  render();
  try {
    if (cloudMode && !topics.some(t => t.keyword === keyword)) {
      if (!topicsReady) throw new Error('키워드 목록을 불러오지 못했습니다. 새로고침해 주세요.');
      await updateTopic({keyword,exclude:[],exact:exactMode});
      if (sequence !== searchSequence) return;
    }
    const params = new URLSearchParams({q:keyword});
    if (topics.some(t => t.keyword === keyword)) params.set('daily','1');
    const result = await readData('search?' + params,controller.signal);
    if (sequence !== searchSequence) return;
    connections = Array.isArray(result.sources) ? result.sources.filter(c => sources[c.source]) : [];
    const observations = Object.fromEntries(connections.map(c => [c.source,c.fetchedAt || result.searchedAt]));
    posts = (Array.isArray(result.posts) ? result.posts : []).filter(validPost).map(p => datedPost(p,observations[p.source] || result.searchedAt));
    searchedAt = result.searchedAt;
    dailyInfo = result.collection || null;
    $('last-updated').textContent = searchedAt ? `${dateTime(searchedAt)} ${dailyInfo ? '수집' : '검색'}` : '첫 수집 대기';
    if (!staticMode && dailyInfo && ['pending','running'].includes(dailyInfo.status)) {
      pollTimer = setTimeout(() => {if (!savedView && currentKeyword === keyword) search(keyword,true);},3000);
    }
  } catch (error) {
    if (sequence !== searchSequence || error.name === 'AbortError') return;
    searchError = error.message || '검색 서버에 연결할 수 없습니다. 잠시 후 다시 검색해 주세요.';
    $('notice').hidden = false; $('last-updated').textContent = '검색 실패';
  } finally {
    if (sequence === searchSequence) {loading = false; render();}
  }
}
function showTopicDialog() {
  if (staticMode) return configureTopics();
  $('topic-input').value = $('keyword').value.trim();
  $('exclude-input').value = topics.find(t => t.keyword === $('topic-input').value)?.exclude.join(', ') || '';
  $('topic-exact').checked = topics.find(t => t.keyword === $('topic-input').value)?.exact ?? $('exact-match').checked;
  $('topic-dialog').showModal(); $('topic-input').focus();
}
$('search-form').addEventListener('submit',async event => {
  event.preventDefault();const keyword=$('keyword').value.trim(),exact=$('exact-match').checked;
  exactSaving=true;render();
  try {await persistExact(keyword,exact);search(keyword,false,exact);}
  catch(error){toast(error.message);}
  finally{exactSaving=false;render();}
});
$('exact-match').addEventListener('change',() => {
  const exact=$('exact-match').checked;
  if($('keyword').value.trim()===currentKeyword)setExactMode(exact);
  else{exactDefault=exact;saveStorage('moa.exact',exact);}
});
document.querySelector('.suggestions').addEventListener('click',event => {const button=event.target.closest('[data-query]');if(button)search(button.dataset.query);});
$('refresh').addEventListener('click',() => {const keyword=currentKeyword || $('keyword').value;if(keyword)search(keyword);else location.reload();});
$('within').addEventListener('input',render);
$('period').addEventListener('change',render);
$('sort').addEventListener('change',render);
$('feed-tabs').addEventListener('click',event => {const button=event.target.closest('[data-tab]');if(button && !button.disabled){activeTab=button.dataset.tab;render();}});
document.querySelectorAll('[data-source-shortcut]').forEach(button => button.addEventListener('click',() => {
  const source = button.dataset.sourceShortcut;
  if (!initialized || !sources[source]) return;
  selected.add(source); activeTab=source; savedView=false;
  $('within').value=''; $('period').value='all'; renderSourceControls(); render();
}));
$('source-controls').addEventListener('change',event => {const source=event.target.dataset.source;if(!sources[source])return;if(event.target.checked)selected.add(source);else selected.delete(source);if(!selected.has(activeTab))activeTab='all';renderSourceControls();render();});
$('feed-nav').addEventListener('click',() => {savedView=false;activeTab='all';$('within').value='';render();});
$('saved-nav').addEventListener('click',() => {savedView=true;activeTab='all';$('within').value='';$('period').value='all';render();});
$('feed').addEventListener('click',event => {
  const button = event.target.closest('[data-bookmark]');
  if (button) {
    const url = button.dataset.bookmark;
    const index = bookmarks.findIndex(p => p.url === url);
    if (index >= 0) {bookmarks.splice(index,1);toast('저장한 글에서 뺐어요.');}
    else {const post=posts.find(p => p.url === url);if(!validPost(post))return;bookmarks.unshift(post);toast('다시 읽을 이야기를 담았어요.');}
    saveStorage('moa.bookmarks',[...bookmarks,...unavailableBookmarks]);render();
  }
  if (event.target.closest('#reset-filters')) {selected.clear();Object.keys(sources).forEach(s => selected.add(s));activeTab='all';$('within').value='';$('period').value='all';if(!savedView && exactMode)setExactMode(false);renderSourceControls();render();}
});
$('topics').addEventListener('click',async event => {
  const remove = event.target.closest('[data-delete]');
  if (remove) {
    if (!topicsReady) return toast('서버의 키워드 목록을 먼저 불러와야 합니다. 새로고침해 주세요.');
    const keyword = topics[Number(remove.dataset.delete)]?.keyword;
    if (!keyword) return;
    remove.disabled = true;
    try {await updateTopic({keyword,delete:true});if(currentKeyword===keyword){clearTimeout(pollTimer);dailyInfo=null;}render();toast('키워드를 삭제하고 다음 자동 수집을 해제했어요.');}
    catch (error) {remove.disabled=false;toast(error.message);}
    return;
  }
  const button = event.target.closest('[data-topic]');
  if (button && topics[Number(button.dataset.topic)]) search(topics[Number(button.dataset.topic)].keyword);
});
$('add-topic').addEventListener('click',showTopicDialog);
$('add-topic-bottom').addEventListener('click',showTopicDialog);
$('close-dialog').addEventListener('click',() => $('topic-dialog').close());
$('topic-dialog').addEventListener('click',event => {if(event.target === $('topic-dialog')) {const rect=event.target.getBoundingClientRect();if(event.clientX<rect.left || event.clientX>rect.right || event.clientY<rect.top || event.clientY>rect.bottom)event.target.close();}});
$('topic-form').addEventListener('submit',async event => {
  event.preventDefault();const keyword=$('topic-input').value.trim();
  if(!keyword)return;
  if(!topicsReady)return toast('서버의 키워드 목록을 먼저 불러와야 합니다. 새로고침해 주세요.');
  const exclude=$('exclude-input').value.split(',').map(s=>s.trim()).filter(Boolean);
  const index=topics.findIndex(t=>t.keyword===keyword);
  if(index<0 && topics.length>=30)return toast('관심 키워드는 최대 30개까지 담을 수 있어요.');
  const button=$('topic-form').querySelector('[type="submit"]');button.disabled=true;
  const buttonLabel=button.textContent;
  if(cloudMode && index<0)button.textContent='등록하고 첫 수집 중…';
  try {await updateTopic({keyword,exclude,exact:$('topic-exact').checked});$('topic-dialog').close();search(keyword);toast('하루 1회 수집할 키워드를 저장했어요.');}
  catch(error){toast(error.message);}
  finally{button.disabled=false;button.textContent=buttonLabel;}
});
$('export').addEventListener('click',() => {
  const data=filteredPosts();if(!data.length)return;
  const cell=value => {let text=String(value??'');if(/^[\s]*[=+\-@]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';};
  const rows=[['소스','제목','미리보기','게시 시각','댓글','조회','검색 방식','원문 URL'],...data.map(p=>[sources[p.source].name,p.title,p.snippet,p.dateInfo.approximate ? `${p.publishedText} (수집 시각 ${p.observedAt} 기준 추정)` : p.published || p.publishedText,p.comments,p.views,p.discovery === 'indexed' ? '공개 웹 검색' : '직접 검색',p.url])];
  const blob=new Blob(['\uFEFF'+rows.map(row=>row.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'});
  const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`모아_${(savedView?'저장한글':currentKeyword).replace(/[<>:"/\\|?*\u0000-\u001f]/g,'_')}_${dateKey(new Date())}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(`${data.length}건을 CSV로 내보냈어요.`);
});
document.addEventListener('keydown',event => {if(event.key==='/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName) && !document.activeElement.isContentEditable && !$('topic-dialog').open){event.preventDefault();$('keyword').focus();$('keyword').select();}});
document.querySelectorAll('[data-select-sources]').forEach(button => button.addEventListener('click',() => {
  selected.clear();
  if (button.dataset.selectSources === 'all') Object.keys(sources).forEach(key => selected.add(key));
  activeTab = 'all'; renderSourceControls(); render();
}));
async function initialize() {
  $('search-button').disabled = true;
  if (cloudMode) {
    try {
      workspaceKey=readStorage('moa.workspace','');
      if(!/^[0-9a-f]{64}$/.test(workspaceKey)) {
        workspaceKey=Array.from(crypto.getRandomValues(new Uint8Array(32)),value=>value.toString(16).padStart(2,'0')).join('');
        localStorage.setItem('moa.workspace',JSON.stringify(workspaceKey));
        localStorage.removeItem('moa.cloudMigrated');
      }
    } catch {toast('키워드를 보관하려면 이 사이트의 브라우저 저장소를 허용해 주세요.');return;}
  }
  const mobileSources = matchMedia('(max-width:767px)');
  const sourcePanel = document.querySelector('.source-section');
  const adaptSourcePanel = () => { sourcePanel.open = !mobileSources.matches; };
  adaptSourcePanel();
  mobileSources.addEventListener('change', adaptSourcePanel);
  try {
    const metadata = await readData('sources');
    const entries = Object.entries(metadata).filter(([key,s]) => /^[a-z0-9_]+$/.test(key) && s && typeof s.name === 'string' && typeof s.domain === 'string' && /^[a-z0-9.-]+$/.test(s.domain));
    if (!entries.length) throw new Error('검색 소스가 없습니다.');
    sources = Object.fromEntries(entries.map(([key,s]) => [key, {...s,color:/^#[0-9a-f]{6}$/i.test(s.color) ? s.color : '#93979e',short:String(s.short || key).slice(0,3),domains:Array.isArray(s.domains) ? s.domains.filter(domain => typeof domain === 'string' && /^[a-z0-9.-]+$/.test(domain)) : []}]));
  } catch {
    toast('전체 소스 목록을 읽지 못해 기본 소스로 시작합니다. 새로고침해 주세요.');
  }
  const previousBookmarks = Array.isArray(storedBookmarks) ? storedBookmarks : [];
  unavailableBookmarks = previousBookmarks.filter(post => post && typeof post.url === 'string' && !sources[post.source]);
  bookmarks = [...new Map(previousBookmarks.filter(validPost).map(post => [post.url,datedPost(post)])).values()];
  selected.clear(); Object.keys(sources).forEach(key => selected.add(key));
  const legacyTopics = topics;
  try {
    const result = await readData('topics');
    if (!Array.isArray(result.topics)) throw new Error('키워드 목록을 읽지 못했습니다.');
    const legacy = topics;
    topics = result.topics;
    const migrationKey=cloudMode ? 'moa.cloudMigrated' : 'moa.topicsMigrated';
    if (!staticMode && !readStorage(migrationKey,false)) {
      for (const topic of legacy) if (!topics.some(t => t.keyword === topic.keyword)) await updateTopic(topic);
      saveStorage(migrationKey,true);
    }
    saveStorage('moa.topics',topics);
    topicsReady = true;
  } catch {
    topics = legacyTopics;
    saveStorage('moa.topics',legacyTopics);
    toast('서버의 관심 키워드를 읽지 못했습니다. 기존 키워드를 유지합니다. 새로고침해 주세요.');
  }
  initialized = true;
  if (staticMode) {
    $('add-topic').setAttribute('aria-label','수집 키워드 설정 (GitHub)');
    $('add-topic-bottom').textContent='수집 키워드 설정 ↗';
    document.querySelector('.topic-schedule').textContent='매일 오전 9시 · 한국시간 · 예약 실행은 지연될 수 있어요.';
    document.querySelector('.local-badge').innerHTML='<i></i> 매일 수집 · GitHub';
    $('search-button').innerHTML='수집 결과 보기 <span>↗</span>';
    $('keyword').value=topics[0]?.keyword || '';
    $('keyword').placeholder='등록한 키워드의 수집 결과 보기';
    $('last-updated').textContent='키워드 등록 대기';
    document.querySelector('.suggestions').innerHTML='<span>등록된 키워드</span>' + topics.slice(0,6).map(topic=>`<button data-query="${escapeHtml(topic.keyword)}">${escapeHtml(topic.keyword)}</button>`).join('');
  }
  if (cloudMode) {
    document.querySelector('.local-badge').innerHTML='<i></i> 바로 등록 · 하루 1회';
    $('search-button').innerHTML='등록·결과 보기 <span>↗</span>';
    $('keyword').value=topics[0]?.keyword || '';
    $('keyword').placeholder='등록하고 바로 수집할 키워드';
    $('last-updated').textContent='키워드 등록 대기';
    $('topic-dialog').querySelector('form > p').textContent='등록 즉시 첫 수집을 시작하고, 완료되면 결과를 보여줍니다. 이후 매일 오전 9시(한국시간)부터 하루 한 번 갱신합니다. 등록 목록은 이 브라우저에 연결됩니다.';
    document.querySelector('.topic-schedule').textContent='첫 등록 즉시 수집 · 이후 매일 오전 9시 · 한국시간';
  }
  renderSourceControls(); render();
  if (storageError) toast('브라우저 저장소를 읽을 수 없어 새 워크스페이스로 시작했어요.');
  if (topics.length || (!staticMode && !cloudMode)) search(topics[0]?.keyword || $('keyword').value);
}
initialize();
