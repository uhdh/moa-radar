"""Persistent daily collection for the single shared workspace (Korean time)."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

KST = timezone(timedelta(hours=9))
HOUR = 9


def collection_result(keyword, row, now, running=False):
    payload = json.loads(row['payload']) if row['payload'] else {'keyword': keyword, 'posts': [], 'sources': [], 'searchedAt': ''}
    status = 'pending'
    if row['day']:
        status = 'error' if row['error'] else 'complete' if row['finished_at'] else 'running' if running else 'interrupted'
    slot = now.replace(hour=HOUR, minute=0, second=0, microsecond=0)
    if row['day'] and row['day'] >= now.date().isoformat():
        slot += timedelta(days=1)
    elif not row['day'] or now >= slot:
        slot = now
    return {**payload, 'collection': {
        'mode': 'daily', 'status': status, 'timezone': 'Asia/Seoul',
        'lastAttemptAt': row['started_at'], 'collectedAt': row['collected_at'],
        'nextRunAt': slot.isoformat(),
        'message': row['error'] or ('수집이 중단되었습니다. 오늘은 재수집하지 않고 다음 일정에 수집합니다.' if status == 'interrupted' else ''),
    }}


class DailyStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.running = set()
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS topics (
                    keyword TEXT PRIMARY KEY, excluded TEXT NOT NULL,
                    exact INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS collections (
                    keyword TEXT PRIMARY KEY, day TEXT NOT NULL,
                    started_at TEXT NOT NULL, finished_at TEXT,
                    collected_at TEXT, payload TEXT, error TEXT NOT NULL DEFAULT ''
                );
            ''')
            if 'exact' not in {row['name'] for row in db.execute('PRAGMA table_info(topics)')}:
                db.execute('ALTER TABLE topics ADD COLUMN exact INTEGER NOT NULL DEFAULT 0')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def topics(self):
        with self.connection() as db:
            return [{'keyword': row['keyword'], 'exclude': json.loads(row['excluded']), 'exact': bool(row['exact'])}
                    for row in db.execute('SELECT * FROM topics ORDER BY rowid')]

    def save_topic(self, keyword, excluded, exact=None):
        with self.connection() as db:
            if not db.execute('SELECT 1 FROM topics WHERE keyword=?', (keyword,)).fetchone() and db.execute('SELECT count(*) FROM topics').fetchone()[0] >= 30:
                raise ValueError('관심 키워드는 최대 30개까지 저장할 수 있습니다.')
            db.execute('''INSERT INTO topics (keyword, excluded, exact) VALUES (?, ?, ?)
                          ON CONFLICT(keyword) DO UPDATE SET excluded=excluded.excluded,
                          exact=CASE WHEN ? IS NULL THEN topics.exact ELSE excluded.exact END''',
                       (keyword, json.dumps(excluded, ensure_ascii=False), int(bool(exact)), exact))

    def delete_topic(self, keyword):
        with self.connection() as db:
            db.execute('DELETE FROM topics WHERE keyword=?', (keyword,))
            # Retain the last attempt so delete/re-add cannot trigger a second collection today.

    def feed(self, keyword, now=None):
        now = (now or datetime.now(KST)).astimezone(KST)
        with self.connection() as db:
            row = db.execute('''SELECT c.* FROM topics t LEFT JOIN collections c
                                ON c.keyword=t.keyword WHERE t.keyword=?''', (keyword,)).fetchone()
        if row is None:
            return None
        return collection_result(keyword, row, now, keyword in self.running)

    def run_due(self, collector, now=None, stop=None):
        for topic in self.topics():
            if stop is not None and stop.is_set():
                break
            current = (now or datetime.now(KST)).astimezone(KST)
            day = current.date().isoformat()
            keyword = topic['keyword']
            with self.connection() as db:
                row = db.execute('SELECT day FROM collections WHERE keyword=?', (keyword,)).fetchone()
                if row and (row['day'] >= day or current.hour < HOUR):
                    continue
                if not db.execute('SELECT 1 FROM topics WHERE keyword=?', (keyword,)).fetchone():
                    continue
                claimed = db.execute('''
                    INSERT INTO collections (keyword, day, started_at) VALUES (?, ?, ?)
                    ON CONFLICT(keyword) DO UPDATE SET day=excluded.day,
                        started_at=excluded.started_at, finished_at=NULL, error=''
                    WHERE collections.day < excluded.day
                ''', (keyword, day, current.isoformat())).rowcount
                if claimed:
                    self.running.add(keyword)
            if not claimed:
                continue
            try:
                payload = collector(keyword)
                if payload['sources'] and not any(source['status'] == 'ok' for source in payload['sources']):
                    raise ValueError('All sources failed')
                with self.connection() as db:
                    db.execute('UPDATE collections SET payload=?, collected_at=?, finished_at=? WHERE keyword=? AND day=?',
                               (json.dumps(payload, ensure_ascii=False), payload['searchedAt'], datetime.now(KST).isoformat(), keyword, day))
            except Exception as exc:
                # Claim is committed before I/O: failed/interrupted attempts also count toward today's limit.
                print(f'Daily collection failed: {type(exc).__name__}', flush=True)
                with self.connection() as db:
                    db.execute('UPDATE collections SET error=?, finished_at=? WHERE keyword=? AND day=?',
                               ('수집을 완료하지 못했습니다. 이전 결과를 유지하며 다음 일정에 다시 수집합니다.', datetime.now(KST).isoformat(), keyword, day))
            finally:
                self.running.discard(keyword)
