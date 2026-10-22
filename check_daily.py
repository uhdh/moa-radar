"""Run `python check_daily.py`: no external requests, temporary SQLite only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from unittest.mock import patch

from daily import DailyStore, KST
import server


def main():
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'radar.sqlite3'
        with closing(sqlite3.connect(path)) as old, old:
            old.execute('CREATE TABLE topics (keyword TEXT PRIMARY KEY, excluded TEXT NOT NULL)')
            old.execute('INSERT INTO topics VALUES (?, ?)', ('스팀','[]'))
        store = DailyStore(path)
        assert store.topics()[0]['exact'] is False, 'Old databases must migrate without removing keywords'
        now = datetime(2026, 10, 22, 8, 30, tzinfo=KST)
        calls = []

        def collect(keyword):
            calls.append(keyword)
            return {'keyword': keyword, 'posts': [{'id': 'post', 'title': str(len(calls))}], 'sources': [], 'searchedAt': now.isoformat()}

        store.save_topic('스팀', [])
        assert store.feed('스팀', now)['collection']['status'] == 'pending'
        store.run_due(collect, now)  # Registration collects once even before 09:00.
        original = store.feed('스팀', now)
        store.run_due(collect, now.replace(hour=9))
        store.save_topic('스팀', ['광고'])  # Changing filters must not collect again.
        store.delete_topic('스팀')
        assert store.feed('스팀', now) is None
        store.save_topic('스팀', ['홍보'])
        store = DailyStore(path)  # Same-day restart and delete/re-add keep the daily claim.
        store.run_due(collect, now.replace(hour=18))
        assert calls == ['스팀']
        assert store.feed('스팀', now)['posts'] == original['posts']
        assert store.topics() == [{'keyword': '스팀', 'exclude': ['홍보'], 'exact': False}]
        store.save_topic('스팀',['홍보'],True)
        store.save_topic('스팀',['홍보'])
        store = DailyStore(path)
        store.run_due(collect,now.replace(hour=19))
        assert store.topics()[0]['exact'] is True and len(calls) == 1
        assert store.feed('스팀',now)['posts'] == original['posts']

        now = now + timedelta(days=1)
        store.run_due(collect, now.replace(hour=8, minute=59))
        assert len(calls) == 1
        # 00:00 UTC is 09:00 KST. Two workers racing must still claim just once.
        at_nine_utc = now.replace(hour=9, minute=0).astimezone(timezone.utc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda s: s.run_due(collect, at_nine_utc), [store, DailyStore(path)]))
        assert len(calls) == 2
        previous = store.feed('스팀', now)['posts']
        now = now + timedelta(days=1)
        with patch('builtins.print'):
            def fail(keyword):
                calls.append(keyword)
                return {'keyword': keyword, 'posts': [], 'sources': [{'status': 'error'}], 'searchedAt': now.isoformat()}
            store.run_due(fail, now.replace(hour=9))
        store.run_due(collect, now.replace(hour=20))
        assert len(calls) == 3 and store.feed('스팀', now)['posts'] == previous
        assert store.feed('스팀', now)['collection']['status'] == 'error'

        now = now + timedelta(days=1)
        def interrupt(keyword):
            raise KeyboardInterrupt()
        try:
            store.run_due(interrupt, now.replace(hour=9))
        except KeyboardInterrupt:
            pass
        store = DailyStore(path)
        store.run_due(collect, now.replace(hour=20))
        assert len(calls) == 3
        assert store.feed('스팀', now)['collection']['status'] == 'interrupted'

        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        base = f'http://127.0.0.1:{httpd.server_port}'
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def request(path, data=None, origin=None):
            headers = {'Content-Type': 'application/json'}
            if origin:
                headers['Origin'] = origin
            req = Request(base + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
            with urlopen(req, timeout=5) as response:
                return json.load(response)

        try:
            with patch.object(server, 'STORE', store), patch.object(server, 'search_all') as live:
                for _ in range(3):
                    saved = request('/api/search?q=' + quote('스팀'))
                    assert saved['posts'] == previous and saved['collection']['mode'] == 'daily'
                assert not live.called, 'Reading or refreshing a saved topic must never scrape.'
                assert len(request('/api/topics')['topics']) == 1
                request('/api/topics', {'keyword': '스팀', 'exclude': ['광고'], 'exact': False})
                assert request('/api/topics')['topics'][0]['exact'] is False
                for data, origin, status in [({'keyword': '스팀'}, 'https://elsewhere.invalid', 403), ({'keyword': '\n'}, None, 400), ({'keyword': '스팀', 'exclude': [12]}, None, 400), ({'keyword':'스팀','exact':'false'},None,400)]:
                    try:
                        request('/api/topics', data, origin)
                        raise AssertionError('Invalid update accepted')
                    except HTTPError as exc:
                        assert exc.code == status
                request('/api/topics', {'keyword': '스팀', 'delete': True})
                assert request('/api/topics')['topics'] == []
                try:
                    request('/api/search?q=' + quote('스팀') + '&daily=1')
                    raise AssertionError('Deleted saved topic must not fall back to live search')
                except HTTPError as exc:
                    assert exc.code == 404
                assert not live.called
                live.return_value = {'keyword': '임시', 'posts': [], 'sources': [], 'searchedAt': now.isoformat()}
                request('/api/search?q=' + quote('임시'))
                assert live.call_count == 1, 'Ad-hoc search should retain its existing behavior.'
        finally:
            httpd.shutdown()
            httpd.server_close()
    print('PASS: initial collection, KST 09:00, concurrent claims, refresh/restart, delete/re-add, failure/interruption, topic API and validation')


if __name__ == '__main__':
    main()
