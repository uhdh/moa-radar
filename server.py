"""Community Radar: public search pages, no account or API key required."""
import argparse
import concurrent.futures
from datetime import datetime, timezone, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import webbrowser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from daily import DailyStore

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
SOURCES = {
    'blog': {'name': '블로그', 'color': '#65b987', 'short': 'bl', 'domain': 'blog.naver.com', 'group': 'naver', 'scope': '네이버 블로그 검색'},
    'cafe': {'name': '카페', 'color': '#bda076', 'short': 'ca', 'domain': 'cafe.naver.com', 'group': 'naver', 'scope': '네이버 카페 공개 검색'},
    'ppomppu': {'name': '뽐뿌', 'color': '#d897b0', 'short': 'pp', 'domain': 'ppomppu.co.kr', 'group': 'community', 'scope': '공개 웹에 색인된 게시글'},
    'clien': {'name': '클리앙', 'color': '#61b5ca', 'short': 'cl', 'domain': 'clien.net', 'group': 'community', 'scope': '통합 검색'},
    'dc': {'name': '디시인사이드', 'color': '#6c8cff', 'short': 'dc', 'domain': 'dcinside.com', 'group': 'community', 'scope': '통합 게시글 검색'},
    'mlbpark': {'name': '엠팍', 'color': '#8e99cb', 'short': 'mp', 'domain': 'mlbpark.donga.com', 'group': 'community', 'scope': '불펜 게시판 검색'},
    'fmkorea': {'name': '에펨코리아', 'color': '#e6ad5c', 'short': 'fm', 'domain': 'fmkorea.com', 'group': 'community', 'scope': '제목·내용 검색'},
    'natepan': {'name': '네이트판', 'color': '#a7b46c', 'short': 'nt', 'domain': 'pann.nate.com', 'group': 'community', 'scope': '톡 검색'},
    'ruliweb': {'name': '루리웹', 'color': '#a999ec', 'short': 'ru', 'domain': 'ruliweb.com', 'group': 'community', 'scope': '유머 게시판 제목 검색'},
    'arca': {'name': '아카라이브', 'color': '#c8ba62', 'short': 'ar', 'domain': 'arca.live', 'group': 'community', 'scope': '공개 웹에 색인된 게시글'},
    'dogdrip': {'name': '개드립', 'color': '#bc8cbe', 'short': 'dg', 'domain': 'dogdrip.net', 'group': 'community', 'scope': '개드립 게시판 검색'},
    'theqoo': {'name': '더쿠', 'color': '#df927b', 'short': 'tq', 'domain': 'theqoo.net', 'group': 'community', 'scope': '공개 웹에 색인된 게시글'},
    'bobaedream': {'name': '보배드림', 'color': '#c4b89b', 'short': 'bb', 'domain': 'bobaedream.co.kr', 'group': 'community', 'scope': '통합 검색의 커뮤니티 영역'},
    'blind': {'name': '블라인드', 'color': '#a7adb6', 'short': 'bd', 'domain': 'teamblind.com', 'group': 'community', 'scope': '공개 게시글 검색'},
    'youtube': {'name': '유튜브', 'color': '#db7b7b', 'short': 'yt', 'domain': 'youtube.com', 'domains': ['youtube.com', 'youtu.be'], 'group': 'social', 'scope': '공개 동영상 · 제목·설명에 키워드 일치'},
    'x': {'name': 'X', 'color': '#c4c7ce', 'short': 'x', 'domain': 'x.com', 'domains': ['x.com', 'twitter.com'], 'group': 'social', 'scope': 'Yahoo 공개 실시간 검색에 노출된 X 게시글'},
    'threads': {'name': 'Threads', 'color': '#b8b3a9', 'short': 'th', 'domain': 'threads.com', 'domains': ['threads.com', 'threads.net'], 'group': 'social', 'scope': '공개 웹 검색 · Threads 신·구 주소의 게시글'},
    'instagram': {'name': '인스타그램', 'color': '#b38ec7', 'short': 'ig', 'domain': 'instagram.com', 'group': 'social', 'scope': '공개 웹 검색 · 로그인 전용 글 제외'},
    'facebook': {'name': '페이스북', 'color': '#7d9ec8', 'short': 'fb', 'domain': 'facebook.com', 'group': 'social', 'scope': '공개 웹 검색 · 로그인 전용 글 제외'},
}
CACHE = {}
LOCK = threading.Lock()
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=len(SOURCES))
STORE = None
DAILY_WAKE = threading.Event()


def valid_keyword(value):
    return isinstance(value, str) and 1 <= len(value.strip()) <= 80 and not any(ord(c) < 32 for c in value)


def search_url(source, keyword):
    q = quote(keyword, safe='')
    return {
        'blog': 'https://search.naver.com/search.naver?' + urlencode({'ssc': 'tab.blog.all', 'query': keyword}),
        'cafe': 'https://search.naver.com/search.naver?' + urlencode({'ssc': 'tab.cafe.all', 'query': keyword}),
        'dc': f'https://search.dcinside.com/post/p/1/sort/latest/q/{q}',
        'clien': f'https://www.clien.net/service/search?q={q}&sort=recency&p=0&boardCd=&isBoard=false',
        'ruliweb': f'https://bbs.ruliweb.com/community/board/300143?search_type=subject&search_key={q}',
        'fmkorea': f'https://www.fmkorea.com/search.php?mid=home&search_keyword={q}&search_target=title_content&sort_index=regdate&order_type=desc',
        'ppomppu': f'https://www.ppomppu.co.kr/search_bbs.php?keyword={q}',
        'mlbpark': f'https://mlbpark.donga.com/mp/b.php?m=search&b=bullpen&query={q}&select=sct',
        'natepan': f'https://pann.nate.com/search/talk?q={q}',
        'arca': f'https://arca.live/b/hotdeal?target=all&keyword={q}',
        'dogdrip': f'https://www.dogdrip.net/index.php?mid=dogdrip&search_target=title_content&search_keyword={q}',
        'theqoo': f'https://theqoo.net/square?search_target=title_content&search_keyword={q}',
        'bobaedream': 'https://www.bobaedream.co.kr/search',
        'blind': f'https://www.teamblind.com/kr/search/{q}',
        'youtube': f'https://www.youtube.com/results?search_query={q}&hl=ko',
        'x': f'https://x.com/search?q={q}&src=typed_query&f=live',
        'threads': f'https://www.threads.com/search?q={q}',
        'instagram': f'https://www.instagram.com/explore/search/keyword/?q={q}',
        'facebook': f'https://www.facebook.com/search/posts/?q={q}',
    }[source]


def text(row, selector):
    el = row.select_one(selector) if selector else None
    return el.get_text(' ', strip=True) if el else ''


def number(value):
    match = re.search(r'([0-9][0-9,.]*)\s*([KkMm만천]?)\s*(?:회|개)?\s*[\])]?$', value.strip())
    if not match:
        return None
    scale = {'k': 1000, 'm': 1000000, '만': 10000, '천': 1000}.get(match[2].lower(), 1)
    try:
        return int(float(match[1].replace(',', '')) * scale)
    except ValueError:
        return None


def post_date(value, now=None):
    now = now or datetime.now(KST)
    value = value.strip().replace('.', '-').replace('/', '-').rstrip('-')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d', '%y-%m-%d %H:%M', '%y- %m- %d'):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.date().isoformat() if '%H' not in fmt else parsed.replace(tzinfo=KST).isoformat()
        except ValueError:
            pass
    if re.fullmatch(r'\d{2}:\d{2}', value):
        h, m = map(int, value.split(':'))
        return now.replace(hour=h, minute=m, second=0, microsecond=0).isoformat()
    return None


def clean_url(source, base, href):
    try:
        url = urlsplit(urljoin(base, href))
    except ValueError:
        return None
    domains = SOURCES[source].get('domains', [SOURCES[source]['domain']])
    if url.scheme not in ('http', 'https') or url.username or url.password or not any(url.hostname == d or (url.hostname or '').endswith('.' + d) for d in domains):
        return None
    # Search state is not part of a post's identity.
    keys = {
        'blog': ('blogId', 'logNo'), 'cafe': ('clubid', 'articleid', 'art'),
        'mlbpark': ('b', 'm', 'id'), 'bobaedream': ('code', 'No'),
        'youtube': ('v',), 'facebook': ('id', 'story_fbid', 'fbid', 'v'),
        'x': (), 'threads': (),
    }.get(source, ('id', 'no', 'document_srl', 'mid'))
    query = {k: v for k, v in parse_qs(url.query).items() if k in keys}
    host, path = url.netloc, url.path
    if source == 'x':
        host = 'x.com'
        path = re.sub(r'/(?:photo|video)/\d+/?$', '', unquote(path)).rstrip('/')
    elif source == 'threads':
        host = 'www.threads.com'
        match = re.match(r'(/@[^/]+/post/[A-Za-z0-9_-]+)', unquote(path))
        if match:
            path = match[1]
    return urlunsplit(('https', host, path, urlencode(query, doseq=True), ''))


def parse_posts(source, html, base):
    if source in ('blog', 'cafe'):
        return parse_naver(source, html)
    if source == 'youtube':
        return parse_youtube(html)
    soup = BeautifulSoup(html, 'html.parser')
    selectors = {
        'dc': ('.sch_result_list li', 'a.tit_txt', '.link_dsc_txt:not(.dsc_sub)', '.date_time', '.sub_txt', '', ''),
        'clien': ('.list_item', 'a.subject_fixed', '.preview', '.timestamp', '.shortname', '.list_reply', '.list_hit .hit'),
        'ruliweb': ('tr.table_body:not(.notice):not(.other)', 'a.subject_link', '', '.time', '.divsn', '.num_reply', '.hit'),
        'fmkorea': ('li.li', '.title a', '', '.regdate', '.category', '.comment_count', ''),
        'mlbpark': ('table.tbl_type01 tbody tr', '.tit a.txt', '', '.date', '.list_word', '.replycnt', '.viewV'),
        'natepan': ('.srch_list .s_list li', 'a.subject', '.txt', '.date', '.part', '.reple-num', ''),
        'dogdrip': ('li.webzine', 'a.title-link', '', '', '', 'h5.title > span', ''),
        'blind': ('.article-list-pre', '.tit h3 a', '.pre-txt', '.past', '.category', '.cmt', '.pv'),
        'bobaedream': ('.search_Community li', 'dt a', '.progress', '.path .next:last-child', '.path .first', '', ''),
    }
    row_sel, title_sel, snippet_sel, date_sel, board_sel, comment_sel, view_sel = selectors[source]
    posts, seen = [], set()
    for row in soup.select(row_sel):
        link = row.select_one(title_sel)
        if not link:
            continue
        url = clean_url(source, base, link.get('href', ''))
        if not url or url in seen:
            continue
        seen.add(url)
        title = text(row, '.ellipsis-target') if source == 'fmkorea' else re.sub(r'\s+', ' ', link.get_text()).strip()
        if not title:
            title = link.get_text(' ', strip=True)
        comments = text(row, comment_sel) if comment_sel else ''
        if source == 'ruliweb' and comments:
            title = re.sub(r'\s*\(\d+\)\s*$', '', title)
        views = text(row, view_sel) if view_sel else ''
        posts.append({
            'id': url, 'url': url, 'source': source, 'title': title[:500],
            'snippet': text(row, snippet_sel)[:500] if snippet_sel else '',
            'published': post_date(text(row, date_sel)) if date_sel else None,
            'publishedText': text(row, date_sel) if date_sel else '',
            'board': text(row, board_sel)[:80],
            'comments': number(re.sub(r'[\[\]()]', '', comments)), 'views': number(views),
        })
    return posts[:25]


def is_post_url(source, url):
    """Exclude profiles, homepages, search pages, and news links from indexed results."""
    parsed = urlsplit(url)
    path, params = parsed.path, parse_qs(parsed.query)
    patterns = {
        'dc': r'/board/view', 'clien': r'/service/board/[^/]+/\d+',
        'ppomppu': r'/zboard/view\.php', 'mlbpark': r'/mp/b\.php',
        'fmkorea': r'/(?:best/)?\d+', 'natepan': r'/talk/\d+',
        'ruliweb': r'/[^?]*/read/\d+', 'arca': r'/b/[^/]+/\d+',
        'dogdrip': r'/(?:[^/]+/)?\d+', 'theqoo': r'/(?:[^/]+/)?\d+',
        'bobaedream': r'/(?:board/bbs/board_view\.php|view)',
        'blind': r'/(?:kr/)?post/[^/]+', 'instagram': r'/(?:p|reel|tv)/[\w-]+',
        'facebook': r'/(?:[^/]+/)?(?:posts|reel|videos|photos)/[^/]+',
        'x': r'^/(?:[^/]+|i/web)/status/\d+/?$',
        'threads': r'^/@[^/]+/post/[A-Za-z0-9_-]+/?$',
    }
    if source == 'blog':
        return bool(re.fullmatch(r'/[^/]+/\d+/?', path) or (path.endswith('/PostView.naver') and params.get('blogId') and params.get('logNo')))
    if source == 'cafe':
        return bool(re.fullmatch(r'/[^/]+/\d+/?', path) or re.search(r'/ca-fe/(?:web|cafes)/.*(?:articles/\d+)', path) or (path.endswith(('/ArticleRead.nhn', '/ArticleRead.naver')) and params.get('clubid') and params.get('articleid')))
    if source == 'youtube':
        return bool((path == '/watch' and re.fullmatch(r'[\w-]{11}', params.get('v', [''])[0])) or re.fullmatch(r'/shorts/[\w-]{11}', path))
    if source == 'facebook' and path in ('/permalink.php', '/story.php'):
        return bool(params.get('story_fbid') and params.get('id'))
    if source in ('mlbpark', 'ppomppu', 'bobaedream', 'dc'):
        required = {'mlbpark': ('id',), 'ppomppu': ('id', 'no'), 'bobaedream': ('code', 'No'), 'dc': ('id', 'no')}[source]
        if not all(params.get(key) for key in required):
            return False
    return bool(re.search(patterns.get(source, r'(?!)'), path))


def visible(element):
    return re.sub(r'\s+', ' ', element.get_text() if element else '').replace('새 창 열림', '').strip()


def parse_naver(source, html):
    soup = BeautifulSoup(html, 'html.parser')
    rows = soup.select('[data-template-id="ugcItem"]') if source == 'blog' else soup.select('.view_wrap')
    posts, seen = [], set()
    for row in rows:
        heading = row.select_one('[class*="text-type-headline"]') if source == 'blog' else row.select_one('a.title_link')
        link = heading.find_parent('a') if heading and heading.name != 'a' else heading
        if not link:
            continue
        url = clean_url(source, search_url(source, ''), link.get('href', ''))
        if not url or url in seen or not is_post_url(source, url):
            continue
        seen.add(url)
        date_text = visible(row.select_one('.sds-comps-profile-info-subtext' if source == 'blog' else '.sub'))
        posts.append({'id': url, 'url': url, 'source': source, 'title': visible(heading)[:500],
                      'snippet': visible(row.select_one('a.fds-ugc-ellipsis2' if source == 'blog' else '.dsc_link'))[:500],
                      'published': post_date(date_text), 'publishedText': date_text,
                      'board': visible(row.select_one('.sds-comps-profile-info-title-text' if source == 'blog' else '.name'))[:80],
                      'comments': None, 'views': None})
    return posts[:25]


def parse_youtube(html):
    match = re.search(r'(?:var\s+ytInitialData\s*=|window\["ytInitialData"\]\s*=)\s*', html)
    if not match:
        raise ValueError('유튜브 검색 데이터가 없습니다.')
    try:
        data, _ = json.JSONDecoder().raw_decode(html[match.end():])
    except (ValueError, RecursionError):
        raise ValueError('유튜브 검색 데이터를 읽을 수 없습니다.')
    def yt_text(value):
        return value.get('simpleText') or ''.join(run.get('text', '') for run in value.get('runs', [])) if isinstance(value, dict) else ''
    stack, posts, seen = [data.get('contents', {})], [], set()
    while stack and len(posts) < 25:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(reversed(node))
        elif isinstance(node, dict):
            item = node.get('videoRenderer')
            if item:
                video_id = item.get('videoId', '')
                title = yt_text(item.get('title'))
                if not re.fullmatch(r'[\w-]{11}', video_id) or video_id in seen or not title:
                    continue
                seen.add(video_id)
                url = 'https://www.youtube.com/watch?v=' + video_id
                snippet = yt_text(item.get('descriptionSnippet')) or ' '.join(yt_text(s.get('snippetText')) for s in item.get('detailedMetadataSnippets', []))
                raw_views = yt_text(item.get('viewCountText'))
                exact_views = re.fullmatch(r'(?:조회수\s*)?([\d,]+)(?:회|\s+views)?', raw_views)
                posts.append({'id': url, 'url': url, 'source': 'youtube', 'title': title[:500], 'snippet': snippet[:500],
                              'published': None, 'publishedText': yt_text(item.get('publishedTimeText')),
                              'board': yt_text(item.get('ownerText'))[:80], 'comments': None,
                              'views': int(exact_views[1].replace(',', '')) if exact_views else None})
            else:
                stack.extend(reversed(list(node.values())))
    return posts


def index_url(source, keyword):
    return 'https://search.naver.com/search.naver?' + urlencode({'where': 'webkr', 'query': keyword + ' site:' + SOURCES[source]['domain']})


def parse_index(source, html):
    soup = BeautifulSoup(html, 'html.parser')
    posts, seen = [], set()
    for row in soup.select('.fds-web-doc-root'):
        heading = row.select_one('[class*="text-type-headline"]')
        link = heading.find_parent('a') if heading else None
        if not link:
            continue
        url = clean_url(source, index_url(source, ''), link.get('href', ''))
        if not url or url in seen or not is_post_url(source, url):
            continue
        seen.add(url)
        # The snippet is another link to the same post, not the site's AI description.
        snippet = ''
        for candidate in row.select('a[href]'):
            if candidate is not link and clean_url(source, '', candidate.get('href', '')) == url:
                value = visible(candidate)
                if value and value != visible(heading):
                    snippet = value
        posts.append({'id': url, 'url': url, 'source': source, 'title': visible(heading)[:500],
                      'snippet': snippet[:500], 'published': None, 'publishedText': '', 'board': '',
                      'comments': None, 'views': None, 'discovery': 'indexed'})
    return posts[:25]


def social_index_urls(source, keyword):
    if source == 'x':
        return ['https://search.yahoo.co.jp/realtime/search?' + urlencode({'p': keyword, 'ei': 'UTF-8'})]
    return ['https://search.yahoo.co.jp/search?' + urlencode({'p': keyword + ' site:' + domain}) for domain in ('threads.com', 'threads.net')]


def parse_social_index(source, html, keyword=''):
    soup = BeautifulSoup(html, 'html.parser')
    rows = soup.select('[class*="Tweet_bodyContainer__"]') if source == 'x' else soup.select('#web ol > li')
    posts, seen = [], set()
    for row in rows:
        link = row.select_one('time a[href]') if source == 'x' else row.select_one(':scope > a[href]')
        if not link:
            continue
        url = clean_url(source, '', link.get('href', ''))
        if not url or url in seen or not is_post_url(source, url):
            continue
        if source == 'x':
            body = visible(row.select_one('p[class*="Tweet_body__"]'))
            title, snippet = body[:120], body[120:620]
            board = visible(row.select_one('[class*="Tweet_authorID__"]'))
            date_text = visible(link)
            reply = re.search(r'(?:^|;)reply:(\d+)', link.get('data-cl-params', ''))
            comments = int(reply[1]) if reply else None
        else:
            title = visible(link)[:500]
            snippet = visible(row.select_one(':scope > div'))
            date = visible(row.select_one('.util-Text--sub'))
            if date and snippet.startswith(date):
                snippet = snippet[len(date):].lstrip(' -')
            board, date_text, comments = '', '', None
        if not title or (keyword and not all(t in (title + ' ' + snippet).casefold() for t in keyword.casefold().split())):
            continue
        seen.add(url)
        posts.append({'id': url, 'url': url, 'source': source, 'title': title,
                      'snippet': snippet[:500], 'published': None, 'publishedText': date_text,
                      'board': board[:80], 'comments': comments, 'views': None, 'discovery': 'indexed'})
    return posts[:25]


def fetch_html(url, data=None, limit=4_000_000):
    request = Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0 (compatible; CommunityRadar/1.0)', 'Accept-Language': 'ko-KR,ko;q=0.9'})
    with urlopen(request, timeout=10) as response:
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('검색 응답이 너무 큽니다')
        encoding = response.headers.get_content_charset()
        if not encoding:
            match = re.search(rb'charset\s*=\s*["\x27]?([a-zA-Z0-9_-]+)', raw[:4096])
            encoding = match[1].decode('ascii') if match else 'utf-8'
        return raw.decode(encoding, errors='replace')


def collect(source, keyword):
    key = (source, keyword)
    with LOCK:
        cached = CACHE.get(key)
        if cached and time.monotonic() - cached[0] < (300 if cached[1]['status'] == 'ok' else 60):
            return {**cached[1], 'cached': True}
    url = search_url(source, keyword)
    result = {'source': source, 'status': 'unavailable', 'posts': [], 'searchUrl': url,
              'method': 'native', 'message': '', 'fetchedAt': datetime.now(KST).isoformat(), 'cached': False}
    indexed_only = source in ('ppomppu', 'arca', 'theqoo', 'instagram', 'facebook', 'x', 'threads')
    if source in ('x', 'threads'):
        found = {}
        for public_url in social_index_urls(source, keyword):
            try:
                for post in parse_social_index(source, fetch_html(public_url), keyword):
                    found.setdefault(post['url'], post)
            except (URLError, TimeoutError, OSError, ValueError, LookupError, RecursionError):
                continue
        if found:
            provider = 'Yahoo 공개 실시간 검색' if source == 'x' else 'Yahoo 공개 웹 검색'
            result.update(status='ok', method='indexed', posts=list(found.values())[:25],
                          message=provider + '에서 수집했습니다. 전체 글이 아니며 지연·누락이 있을 수 있습니다.')
    if not indexed_only:
        try:
            data = urlencode({'keyword': keyword}).encode() if source == 'bobaedream' else None
            html = fetch_html(url, data=data, limit=8_000_000 if source == 'youtube' else 4_000_000)
            posts = parse_posts(source, html, url)
            if source == 'youtube':
                # ponytail: literal title/snippet matching excludes unrelated recommendations; add transcript search for hidden matches.
                tokens = keyword.casefold().split()
                posts = [p for p in posts if all(t in (p['title'] + ' ' + p['snippet']).casefold() for t in tokens)]
            empty = False
            if not posts:
                soup = BeautifulSoup(html, 'html.parser')
                soup_text = soup.get_text(' ', strip=True)
                empty = any(s in soup_text for s in ('검색결과가 없습니다', '검색 결과가 없습니다', '검색된 글이 없습니다', '검색된 게시물이 없습니다', '검색된 게시글이 없습니다', '검색 결과 없음', '검색결과 없음', '결과값이 없습니다', 'No results found'))
                if source == 'youtube' and re.search(r'var\s+ytInitialData\s*=', html):
                    empty = True
                if source in ('fmkorea', 'dogdrip'):
                    field = soup.select_one('input[name="search_keyword"]')
                    area = '.fm_best_widget > ul' if source == 'fmkorea' else '.board-list'
                    empty = empty or bool(field and field.get('value') == keyword and soup.select_one(area))
            if posts or empty:
                result.update(status='ok', posts=[dict(p, discovery='native') for p in posts])
            else:
                result['message'] = '직접 검색 결과를 읽지 못했습니다.'
        except HTTPError as exc:
            result['message'] = '직접 검색 접근 제한' if exc.code in (403, 429, 430) else f'직접 검색 응답 오류 ({exc.code})'
        except (URLError, TimeoutError, OSError, ValueError, LookupError, RecursionError):
            result['message'] = '직접 검색에 연결하거나 응답을 읽을 수 없습니다.'
    if result['status'] != 'ok':
        result['method'] = 'indexed'
        try:
            html = fetch_html(index_url(source, keyword))
            posts = parse_index(source, html)
            if posts:
                result.update(status='ok', posts=posts, message='공개 웹에 색인된 글만 수집합니다. 최신·비공개 글은 누락될 수 있습니다.')
            else:
                result['message'] = '공개 웹 검색에서 확인된 게시글이 없습니다. 로그인 전용 글과 계정 소개 페이지는 수집하지 않습니다.'
        except (URLError, TimeoutError, OSError, ValueError, LookupError, RecursionError):
            result.update(status='error', message='직접 검색과 공개 웹 검색에 연결할 수 없습니다.')
    result['fetchedAt'] = datetime.now(KST).isoformat()
    with LOCK:
        # ponytail: one-process cache, at most 100 source/query pairs; share it if deploying multiple workers.
        if len(CACHE) >= 100:
            CACHE.pop(next(iter(CACHE)))
        CACHE[key] = (time.monotonic(), result)
    return result


def search_all(keyword):
    futures = [POOL.submit(collect, source, keyword) for source in SOURCES]
    results = [future.result() for future in futures]
    posts = {p['id']: p for r in results for p in r['posts']}
    statuses = [{k: v for k, v in r.items() if k != 'posts'} for r in results]
    return {'keyword': keyword, 'posts': list(posts.values()), 'sources': statuses,
            'searchedAt': datetime.now(KST).isoformat()}


def daily_worker(stop):
    # ponytail: one scheduler and local SQLite; use a shared database before running multiple replicas.
    while not stop.is_set():
        try:
            STORE.run_due(search_all, stop=stop)
        except Exception as exc:
            print(f'Daily scheduler error: {type(exc).__name__}', flush=True)
        DAILY_WAKE.wait(60)
        DAILY_WAKE.clear()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'public'), **kwargs)

    def json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == '/api/sources':
            return self.json(SOURCES)
        if parsed.path == '/api/topics':
            return self.json({'topics': STORE.topics()})
        if parsed.path == '/api/search':
            query = parse_qs(parsed.query)
            keyword = query.get('q', [''])[0].strip()
            if not valid_keyword(keyword):
                return self.json({'error': '검색어는 1~80자로 입력해 주세요.'}, 400)
            daily = STORE.feed(keyword) if STORE else None
            if daily is not None:
                return self.json(daily)
            if query.get('daily') == ['1']:
                return self.json({'error': '삭제된 관심 키워드입니다. 새로고침해 주세요.'}, 404)
            return self.json(search_all(keyword))
        if parsed.path.startswith('/api/'):
            return self.json({'error': '존재하지 않는 API입니다.'}, 404)
        return super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != '/api/topics':
            return self.json({'error': '존재하지 않는 API입니다.'}, 404)
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            return self.json({'error': '이 사이트에서만 키워드를 변경할 수 있습니다.'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if self.headers.get_content_type() != 'application/json' or not 0 < length <= 16384:
                raise ValueError('키워드 요청 형식이 올바르지 않습니다.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or not valid_keyword(data.get('keyword')):
                raise ValueError('키워드는 1~80자로 입력해 주세요.')
            keyword = data['keyword'].strip()
            if data.get('delete') is True:
                STORE.delete_topic(keyword)
            else:
                excluded = data.get('exclude', [])
                if not isinstance(excluded, list) or len(excluded) > 30 or any(not isinstance(word, str) or not 1 <= len(word.strip()) <= 80 for word in excluded):
                    raise ValueError('제외 단어는 1~80자, 최대 30개로 입력해 주세요.')
                if 'exact' in data and not isinstance(data['exact'], bool):
                    raise ValueError('정확한 단어 검색 설정은 체크 여부로 지정해 주세요.')
                STORE.save_topic(keyword, [word.strip() for word in excluded], data.get('exact'))
                DAILY_WAKE.set()
        except (ValueError, UnicodeError) as exc:
            return self.json({'error': str(exc)}, 400)
        except (OSError, sqlite3.Error):
            return self.json({'error': '키워드를 저장하지 못했습니다. 저장 공간을 확인해 주세요.'}, 503)
        return self.json({'topics': STORE.topics()})

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        super().end_headers()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--open', action='store_true', help='Open the app in the default browser')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data', help='Persistent directory for saved topics and daily results')
    args = parser.parse_args()
    STORE = DailyStore(args.data_dir / 'radar.sqlite3')
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    stop = threading.Event()
    worker = threading.Thread(target=daily_worker, args=(stop,), daemon=True)
    worker.start()
    print(f'Community Radar: http://{args.host}:{args.port}', flush=True)
    if args.open:
        webbrowser.open(f'http://{args.host}:{args.port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        DAILY_WAKE.set()
        worker.join(timeout=45)
        server.server_close()
