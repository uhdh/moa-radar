"""Collect once per Korean day and build the GitHub Pages snapshot."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

from daily import DailyStore, KST
from server import SOURCES, search_all, valid_keyword

ROOT = Path(__file__).resolve().parent


def read_topics(path):
    topics = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(topics, list) or len(topics) > 30:
        raise ValueError('keywords.json must be an array with at most 30 keywords')
    result = []
    for topic in topics:
        if not isinstance(topic, dict) or not valid_keyword(topic.get('keyword')):
            raise ValueError('Each keyword must contain 1-80 characters')
        keyword = topic['keyword'].strip()
        excluded, exact = topic.get('exclude', []), topic.get('exact', False)
        if not isinstance(exact, bool) or not isinstance(excluded, list) or len(excluded) > 30 or any(not valid_keyword(word) for word in excluded):
            raise ValueError('Invalid exclude or exact setting')
        if any(row['keyword'] == keyword for row in result):
            raise ValueError('Duplicate keyword')
        result.append({'keyword': keyword, 'exclude': [word.strip() for word in excluded], 'exact': exact})
    return result


def load_store(database, state, topics):
    store = DailyStore(database)
    if state.exists():
        rows = json.loads(state.read_text(encoding='utf-8'))
        with store.connection() as db:
            for row in rows:
                db.execute('''INSERT INTO collections
                    (keyword, day, started_at, finished_at, collected_at, payload, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (row['keyword'], row['day'], row['started_at'], row['finished_at'], row['collected_at'],
                     json.dumps(row['payload'], ensure_ascii=False) if row['payload'] is not None else None, row['error']))
    for topic in topics:
        store.save_topic(topic['keyword'], topic['exclude'], topic['exact'])
    return store


def save_state(store, path, push=False):
    with store.connection() as db:
        rows = [dict(row) for row in db.execute('SELECT * FROM collections ORDER BY keyword')]
    active = {topic['keyword'] for topic in store.topics()}
    today = datetime.now(KST).date().isoformat()
    rows = [row for row in rows if row['keyword'] in active or row['day'] >= today]
    for row in rows:
        row['payload'] = json.loads(row['payload']) if row['payload'] else None
        if row['keyword'] not in active:
            row['payload'] = None
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    if push:
        relative = path.resolve().relative_to(ROOT).as_posix()
        def git(*args):
            return subprocess.run(['git', *args], cwd=ROOT, check=True)
        git('add', '--', relative)
        changed = subprocess.run(['git', 'diff', '--cached', '--quiet', '--', relative], cwd=ROOT).returncode
        if changed not in (0, 1):
            raise RuntimeError('Cannot inspect collection state')
        if changed:
            git('-c', 'user.name=github-actions[bot]', '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
                'commit', '-m', 'Update daily collection state', '--', relative)
            git('push', 'origin', 'HEAD:main')


def build_site(store, destination, repository):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid GitHub repository')
    shutil.copytree(ROOT / 'public', destination, dirs_exist_ok=True)
    index = destination / 'index.html'
    index.write_text(index.read_text(encoding='utf-8').replace('<html lang="ko">', '<html lang="ko" data-mode="static">'), encoding='utf-8')
    # ponytail: one snapshot for <=30 keywords; split by keyword if download size becomes a problem.
    snapshot = {'schema': 1, 'generatedAt': datetime.now(KST).isoformat(), 'repository': repository,
                'sources': SOURCES, 'topics': store.topics(),
                'feeds': {topic['keyword']: store.feed(topic['keyword']) for topic in store.topics()}}
    (destination / 'snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
    (destination / '.nojekyll').touch()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / '_site')
    parser.add_argument('--state', type=Path, default=ROOT / 'state/collections.json')
    parser.add_argument('--keywords', type=Path, default=ROOT / 'keywords.json')
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--push-state', action='store_true')
    args = parser.parse_args()
    topics = read_topics(args.keywords)
    with TemporaryDirectory() as temporary:
        store = load_store(Path(temporary) / 'radar.sqlite3', args.state, topics)
        if args.collect:
            def collect(keyword):
                # Persist the claim remotely BEFORE network I/O, including on manual reruns/restarts.
                # Failed pushes abort collection, so an unrecorded attempt cannot bypass the daily limit.
                save_state(store, args.state, args.push_state)
                return search_all(keyword)
            try:
                store.run_due(collect)
            finally:
                save_state(store, args.state, args.push_state)
        build_site(store, args.output, args.repository)
        failed = [topic['keyword'] for topic in topics if store.feed(topic['keyword'])['collection']['status'] in ('error', 'interrupted')]
        print(f'Built {len(topics)} keywords; collection errors: {len(failed)}')
        if failed:
            # The previous snapshot is still deployed; report degraded collection in the Actions summary.
            print('::warning::Some keywords could not be collected; previous results retained.')


if __name__ == '__main__':
    main()
