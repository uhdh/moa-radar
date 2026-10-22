"""GitHub Actions daily trigger. The API owns the durable once-per-day claim."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main():
    base = os.environ['MOA_API_URL'].rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname.endswith('.vercel.app') or parsed.path:
        raise ValueError('Invalid API URL')
    headers = {'Authorization': 'Bearer ' + os.environ['MOA_CRON_SECRET'], 'Content-Type': 'application/json'}
    def request(data=None):
        body = json.dumps(data).encode() if data is not None else None
        with urlopen(Request(base + '/api/scheduled', headers=headers, data=body), timeout=150) as response:
            return json.load(response)
    keywords = request()['keywords']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda keyword: request({'keyword':keyword}), keywords))
    print(f'Daily schedule: {len(keywords)} keywords, {sum(result["attempted"] for result in results)} new attempts')


if __name__ == '__main__':
    main()
