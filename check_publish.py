"""Runnable check for persistent Actions claims and static Pages output."""
from datetime import datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from daily import KST
from publish import build_site, load_store, read_topics, save_state


def main():
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        config, state = root / 'keywords.json', root / 'state.json'
        config.write_text('[{"keyword":"스팀","exclude":[],"exact":false}]', encoding='utf-8')
        topics = read_topics(config)
        store = load_store(root / 'first.sqlite3', state, topics)
        calls = []
        now = datetime.now(KST).replace(hour=10)
        def collect(keyword):
            save_state(store, state)
            # A new runner sees the committed claim, even before collection finishes.
            restart = load_store(root / 'during.sqlite3', state, topics)
            restart.run_due(lambda word: calls.append('DUPLICATE'), now)
            assert restart.feed(keyword, now)['collection']['status'] == 'interrupted'
            calls.append(keyword)
            return {'keyword': keyword, 'posts': [], 'sources': [{'source':'dc','status':'ok'}], 'searchedAt':now.isoformat()}
        store.run_due(collect, now)
        save_state(store, state)
        restart = load_store(root / 'after.sqlite3', state, topics)
        restart.run_due(lambda keyword: calls.append('DUPLICATE'), now)
        assert calls == ['스팀']
        assert restart.feed('스팀', now)['collection']['status'] == 'complete'
        build_site(restart, root / 'site', 'uhdh/moa-radar')
        snapshot = json.loads((root / 'site/snapshot.json').read_text(encoding='utf-8'))
        assert snapshot['topics'] == topics and snapshot['feeds']['스팀']['collection']['status'] == 'complete'
        html = (root / 'site/index.html').read_text(encoding='utf-8')
        assert 'data-mode="static"' in html and 'href="./style.css"' in html and 'src="/app.js"' not in html
        assert len(snapshot['sources']) == 19
        build_site(restart,root/'cloud','uhdh/moa-radar','https://moa-radar-api.vercel.app')
        assert 'data-mode="cloud" data-api="https://moa-radar-api.vercel.app"' in (root/'cloud/index.html').read_text(encoding='utf-8')
        # Retain today's claim after delete/re-add, but do not publish deleted keyword data.
        removed = load_store(root / 'removed.sqlite3', state, [])
        save_state(removed, state)
        assert json.loads(state.read_text(encoding='utf-8'))[0]['payload'] is None
        readded = load_store(root / 'readded.sqlite3', state, topics)
        readded.run_due(lambda keyword: calls.append('DUPLICATE'), now)
        assert calls == ['스팀']
        readded.run_due(lambda keyword: {'keyword':keyword,'posts':[],'sources':[],'searchedAt':now.isoformat()}, now + timedelta(days=1))
        assert readded.feed('스팀',now + timedelta(days=1))['collection']['status'] == 'complete'
        build_site(removed, root / 'empty', 'uhdh/moa-radar')
        empty = json.loads((root / 'empty/snapshot.json').read_text(encoding='utf-8'))
        assert empty['topics'] == [] and empty['feeds'] == {}
        for value in ['{}','[{}]','[{"keyword":"x","exact":"false"}]','[{"keyword":"x","exclude":[3]}]','[{"keyword":"x"},{"keyword":"x"}]']:
            config.write_text(value, encoding='utf-8')
            try:
                read_topics(config)
                raise AssertionError('Invalid config accepted')
            except ValueError:
                pass
        with patch('publish.ROOT',root), patch('publish.subprocess.run', side_effect=RuntimeError('push failed')):
            try:
                save_state(store, state, push=True)
                raise AssertionError('Push error hidden')
            except RuntimeError as exc:
                assert str(exc) == 'push failed'
    print('PASS: durable daily claims, restart/delete/re-add, static subpath assets, empty deployment and config validation')


if __name__ == '__main__':
    main()
