"""Vercel API: browser-owned topics and durable, shared daily collection claims."""
from datetime import datetime, timedelta
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler
import json
import os
import re
from urllib.parse import parse_qs, urlsplit

import psycopg
from psycopg.rows import dict_row

from daily import KST, HOUR, collection_result
from server import SOURCES, search_all, valid_keyword


def connection():
    return psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=10, row_factory=dict_row)


def initialize():
    with connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS cloud_topics (
            owner TEXT NOT NULL, keyword TEXT NOT NULL, excluded TEXT NOT NULL,
            exact BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(owner, keyword))''')
        db.execute('''CREATE TABLE IF NOT EXISTS cloud_collections (
            keyword TEXT PRIMARY KEY, day TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, collected_at TEXT, payload TEXT, error TEXT NOT NULL DEFAULT '')''')
        db.execute('''CREATE TABLE IF NOT EXISTS cloud_registrations (
            day TEXT NOT NULL, ip TEXT NOT NULL, count INTEGER NOT NULL,
            PRIMARY KEY(day, ip))''')


def topics(owner):
    with connection() as db:
        rows = db.execute('SELECT keyword, excluded, exact FROM cloud_topics WHERE owner=%s ORDER BY created_at,keyword', (owner,)).fetchall()
    return [{'keyword': row['keyword'], 'exclude': json.loads(row['excluded']), 'exact': row['exact']} for row in rows]


def save_topic(owner, keyword, excluded, exact, ip):
    today = datetime.now(KST).date().isoformat()
    with connection() as db:
        # ponytail: one short registration lock and 30 active queries globally; expand quotas for a multi-user service.
        db.execute('SELECT pg_advisory_xact_lock(5177067)')
        exists = db.execute('SELECT 1 FROM cloud_topics WHERE owner=%s AND keyword=%s', (owner, keyword)).fetchone()
        if not exists:
            if db.execute('SELECT count(*) AS n FROM cloud_topics WHERE owner=%s', (owner,)).fetchone()['n'] >= 30:
                raise ValueError('관심 키워드는 최대 30개까지 저장할 수 있습니다.')
            total = db.execute('SELECT count(*) AS n, count(DISTINCT keyword) AS keywords FROM cloud_topics').fetchone()
            if total['n'] >= 300 or (total['keywords'] >= 30 and not db.execute('SELECT 1 FROM cloud_topics WHERE keyword=%s LIMIT 1', (keyword,)).fetchone()):
                raise ValueError('현재 서비스의 수집 한도에 도달했습니다. 사용하지 않는 키워드를 삭제해 주세요.')
            ip_count = db.execute('SELECT count FROM cloud_registrations WHERE day=%s AND ip=%s', (today, ip)).fetchone()
            total_count = db.execute('SELECT coalesce(sum(count),0) AS n FROM cloud_registrations WHERE day=%s', (today,)).fetchone()['n']
            if (ip_count and ip_count['count'] >= 30) or total_count >= 100:
                raise ValueError('오늘의 새 키워드 등록 한도에 도달했습니다. 기존 결과는 계속 볼 수 있습니다.')
            db.execute('''INSERT INTO cloud_registrations VALUES (%s,%s,1)
                ON CONFLICT(day,ip) DO UPDATE SET count=cloud_registrations.count+1''', (today, ip))
        db.execute('''INSERT INTO cloud_topics(owner,keyword,excluded,exact) VALUES (%s,%s,%s,%s)
            ON CONFLICT(owner,keyword) DO UPDATE SET excluded=EXCLUDED.excluded,
            exact=CASE WHEN %s IS NULL THEN cloud_topics.exact ELSE EXCLUDED.exact END''',
            (owner, keyword, json.dumps(excluded, ensure_ascii=False), bool(exact), exact))
        db.execute('''DELETE FROM cloud_collections c WHERE c.day<%s
            AND NOT EXISTS(SELECT 1 FROM cloud_topics t WHERE t.keyword=c.keyword)''', (today,))
        db.execute('DELETE FROM cloud_registrations WHERE day<%s', (today,))


def delete_topic(owner, keyword):
    with connection() as db:
        db.execute('DELETE FROM cloud_topics WHERE owner=%s AND keyword=%s', (owner, keyword))
        # Preserve today's collection claim, including delete/re-add from another browser.


def feed(owner, keyword, now=None):
    current = (now or datetime.now(KST)).astimezone(KST)
    with connection() as db:
        row = db.execute('''SELECT c.* FROM cloud_topics t LEFT JOIN cloud_collections c ON c.keyword=t.keyword
            WHERE t.owner=%s AND t.keyword=%s''', (owner, keyword)).fetchone()
    if row is None:
        return None
    running = bool(row['started_at'] and not row['finished_at'] and
                   current - datetime.fromisoformat(row['started_at']) < timedelta(minutes=3))
    return collection_result(keyword, row, current, running)


def collect_one(keyword, collector=search_all, now=None):
    current = (now or datetime.now(KST)).astimezone(KST)
    day, started = current.date().isoformat(), current.isoformat()
    with connection() as db:
        claimed = db.execute('''INSERT INTO cloud_collections(keyword,day,started_at)
            SELECT %s,%s,%s WHERE EXISTS(SELECT 1 FROM cloud_topics WHERE keyword=%s)
            ON CONFLICT(keyword) DO UPDATE SET day=EXCLUDED.day, started_at=EXCLUDED.started_at,
                finished_at=NULL, error=''
            WHERE cloud_collections.day<EXCLUDED.day AND %s
            RETURNING keyword''', (keyword, day, started, keyword, current.hour >= HOUR)).fetchone()
    if not claimed:
        return False
    # The PostgreSQL transaction commits BEFORE I/O. Parallel requests and cold starts share this claim.
    try:
        result = collector(keyword)
        if not any(source['status'] == 'ok' for source in result['sources']):
            raise ValueError('All sources failed')
        with connection() as db:
            db.execute('''UPDATE cloud_collections SET payload=%s,collected_at=%s,finished_at=%s
                WHERE keyword=%s AND day=%s AND started_at=%s''',
                (json.dumps(result, ensure_ascii=False), result['searchedAt'], datetime.now(KST).isoformat(), keyword, day, started))
    except Exception as exc:
        print(f'Collection failed: {type(exc).__name__}', flush=True)
        with connection() as db:
            db.execute('''UPDATE cloud_collections SET error=%s,finished_at=%s
                WHERE keyword=%s AND day=%s AND started_at=%s''',
                ('수집을 완료하지 못했습니다. 이전 결과를 유지하며 다음 일정에 다시 수집합니다.', datetime.now(KST).isoformat(), keyword, day, started))
    return True


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not log keywords, browser credentials or request bodies.

    def route(self):
        parsed = urlsplit(self.path)
        route = parse_qs(parsed.query).get('route', [None])[0]
        return ('/api/' + route if route is not None else parsed.path), parse_qs(parsed.query)

    def allowed_origin(self):
        origin = self.headers.get('Origin', '')
        allowed = {'https://uhdh.github.io', 'https://' + self.headers.get('Host', '')}
        if not os.environ.get('VERCEL'):
            allowed |= {'http://127.0.0.1:8789', 'http://127.0.0.1:8790'}
        return not origin or origin in allowed

    def json(self, data, status=200):
        encoded = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Length', str(len(encoded)))
        if self.headers.get('Origin') and self.allowed_origin():
            self.send_header('Access-Control-Allow-Origin', self.headers['Origin'])
            self.send_header('Vary', 'Origin')
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self):
        if not self.allowed_origin():
            return self.json({'error': '허용되지 않은 사이트입니다.'}, 403)
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', self.headers.get('Origin', 'https://uhdh.github.io'))
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization,Content-Type')
        self.send_header('Access-Control-Max-Age', '3600')
        self.send_header('Vary', 'Origin')
        self.end_headers()

    def body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if self.headers.get_content_type() != 'application/json' or not 0 < length <= 16384:
            raise ValueError('요청 형식이 올바르지 않습니다.')
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError('요청 형식이 올바르지 않습니다.')
        return data

    def dispatch(self, post=False):
        if not self.allowed_origin():
            return self.json({'error': '허용되지 않은 사이트입니다.'}, 403)
        path, query = self.route()
        if path == '/api/sources' and not post:
            return self.json(SOURCES)
        credential = self.headers.get('Authorization', '').removeprefix('Bearer ')
        if path == '/api/scheduled':
            secret = os.environ.get('CRON_SECRET', '')
            if not secret or not hmac.compare_digest(credential.encode(), secret.encode()):
                return self.json({'error': '인증이 필요합니다.'}, 401)
            if post:
                keyword = self.body().get('keyword')
                if not valid_keyword(keyword):
                    raise ValueError('키워드는 1~80자로 입력해 주세요.')
                attempted = collect_one(keyword.strip())
                return self.json({'attempted': attempted})
            with connection() as db:
                keywords = [row['keyword'] for row in db.execute('SELECT DISTINCT keyword FROM cloud_topics ORDER BY keyword')]
            return self.json({'keywords': keywords})
        if not re.fullmatch(r'[0-9a-f]{64}', credential):
            return self.json({'error': '브라우저 저장소를 사용할 수 없습니다. 저장소를 허용한 뒤 새로고침해 주세요.'}, 401)
        owner = hashlib.sha256(credential.encode()).hexdigest()
        if path == '/api/topics':
            if post:
                data = self.body()
                keyword = data.get('keyword')
                if not valid_keyword(keyword):
                    raise ValueError('키워드는 1~80자로 입력해 주세요.')
                keyword = keyword.strip()
                if data.get('delete') is True:
                    delete_topic(owner, keyword)
                else:
                    excluded = data.get('exclude', [])
                    exact = data.get('exact')
                    if not isinstance(excluded, list) or len(excluded) > 30 or any(not valid_keyword(word) for word in excluded) or ('exact' in data and not isinstance(exact, bool)):
                        raise ValueError('제외 단어 또는 정확한 단어 설정이 올바르지 않습니다.')
                    address = self.headers.get('x-vercel-forwarded-for', self.client_address[0]).split(',')[0].strip()
                    ip = hmac.new(os.environ['CRON_SECRET'].encode(), address.encode(), hashlib.sha256).hexdigest()
                    save_topic(owner, keyword, [word.strip() for word in excluded], exact, ip)
                    collect_one(keyword)
            return self.json({'topics': topics(owner)})
        if path == '/api/search' and not post:
            keyword = query.get('q', [''])[0].strip()
            if not valid_keyword(keyword):
                raise ValueError('키워드는 1~80자로 입력해 주세요.')
            result = feed(owner, keyword)
            return self.json(result) if result is not None else self.json({'error': '등록되지 않았거나 삭제된 키워드입니다.'}, 404)
        return self.json({'error': '존재하지 않는 API입니다.'}, 404)

    def serve_api(self, post=False):
        try:
            self.dispatch(post)
        except (ValueError, UnicodeError) as exc:
            self.json({'error': str(exc) if not isinstance(exc, UnicodeError) else '문자 인코딩을 확인해 주세요.'}, 400)
        except (psycopg.Error, OSError, KeyError) as exc:
            print(f'API unavailable: {type(exc).__name__}', flush=True)
            self.json({'error': '수집 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'}, 503)

    def do_GET(self):
        self.serve_api()

    def do_POST(self):
        self.serve_api(True)


if __name__ == '__main__':
    initialize()
    print('Cloud database initialized')
