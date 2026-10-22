"""Live PostgreSQL check. Uses unique test rows and removes only those rows."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
import secrets
import threading
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import cloud
from daily import KST


def main():
    if not os.environ.get('DATABASE_URL') or not os.environ.get('CRON_SECRET'):
        raise RuntimeError('Set DATABASE_URL and CRON_SECRET for this check')
    cloud.initialize()
    token, other = secrets.token_hex(32), secrets.token_hex(32)
    owner = hashlib.sha256(token.encode()).hexdigest()
    second = hashlib.sha256(other.encode()).hexdigest()
    keyword = '__check_' + secrets.token_hex(8)
    ip = '__check_' + secrets.token_hex(8)
    now = datetime.now(KST).replace(hour=10)
    calls = []
    def collect(word):
        calls.append(word)
        return {'keyword':word, 'posts':[{'title':'check'}], 'sources':[{'source':'dc','status':'ok'}], 'searchedAt':now.isoformat()}
    httpd = None
    try:
        cloud.save_topic(owner, keyword, [], False, ip)
        assert cloud.topics(second) == [] and cloud.feed(second, keyword) is None
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempted = list(pool.map(lambda _:cloud.collect_one(keyword,collect,now),range(2)))
        assert sorted(attempted)==[False,True] and calls==[keyword]
        original=cloud.feed(owner,keyword,now)
        assert original['collection']['status']=='complete'
        for _ in range(3):assert cloud.feed(owner,keyword,now)==original
        cloud.save_topic(owner,keyword,['홍보'],True,ip)
        assert not cloud.collect_one(keyword,collect,now)
        assert cloud.topics(owner)[0]['exact'] is True
        cloud.delete_topic(owner,keyword)
        cloud.save_topic(owner,keyword,[],False,ip)
        cloud.save_topic(second,keyword,[],False,ip)
        assert not cloud.collect_one(keyword,collect,now) and len(calls)==1
        tomorrow=now+timedelta(days=1)
        assert not cloud.collect_one(keyword,collect,tomorrow.replace(hour=8))
        assert cloud.collect_one(keyword,collect,tomorrow.replace(hour=9)) and len(calls)==2
        with patch('builtins.print'):
            cloud.collect_one(keyword,lambda word:(_ for _ in ()).throw(ValueError('failed')),tomorrow+timedelta(days=1))
        assert not cloud.collect_one(keyword,collect,tomorrow+timedelta(days=1))
        failed=cloud.feed(owner,keyword,tomorrow+timedelta(days=1))
        assert failed['collection']['status']=='error' and failed['posts']==original['posts']
        # An interrupted process retains its claim across new instances.
        with cloud.connection() as db:
            db.execute('UPDATE cloud_collections SET finished_at=NULL,error=%s,started_at=%s WHERE keyword=%s',('',(now-timedelta(minutes=5)).isoformat(),keyword))
        assert cloud.feed(owner,keyword,now)['collection']['status']=='interrupted'

        httpd=ThreadingHTTPServer(('127.0.0.1',0),cloud.handler)
        threading.Thread(target=httpd.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{httpd.server_port}'
        def request(path,data=None,credential=token,origin='https://uhdh.github.io',method=None):
            headers={'Content-Type':'application/json','Origin':origin}
            if credential:headers['Authorization']='Bearer '+credential
            body=json.dumps(data).encode() if data is not None else None
            with urlopen(Request(base+path,data=body,headers=headers,method=method),timeout=5) as response:
                raw=response.read()
                return (json.loads(raw) if raw else None,response.headers)
        with patch('cloud.collect_one') as scraper:
            assert request('/api/topics')[0]['topics'][0]['keyword']==keyword
            assert request('/api/topics',credential=other)[0]['topics'][0]['keyword']==keyword
            assert request('/api/search?q='+quote(keyword))[0]['posts']==original['posts']
            assert not scraper.called
        assert request('/api/topics',{'keyword':keyword,'exact':True,'exclude':[]})[0]['topics'][0]['exact'] is True
        assert request('/api/index?route=topics')[0]['topics'][0]['keyword']==keyword
        assert request('/api/topics',method='OPTIONS')[1]['Access-Control-Allow-Origin']=='https://uhdh.github.io'
        for path,data,credential,origin,status in [
            ('/api/topics',None,'','https://uhdh.github.io',401),
            ('/api/topics',None,token,'https://elsewhere.invalid',403),
            ('/api/topics',{'keyword':'\n'},token,'https://uhdh.github.io',400),
            ('/api/topics',{'keyword':keyword,'exact':None},token,'https://uhdh.github.io',400),
            ('/api/scheduled',None,token,'https://uhdh.github.io',401),
            ('/api/search?q=other',None,token,'https://uhdh.github.io',404),
        ]:
            try:
                request(path,data,credential,origin)
                raise AssertionError('Invalid request accepted')
            except HTTPError as exc:assert exc.code==status
        assert keyword in request('/api/scheduled',credential=os.environ['CRON_SECRET'])[0]['keywords']
    finally:
        if httpd:httpd.shutdown();httpd.server_close()
        with cloud.connection() as db:
            db.execute('DELETE FROM cloud_topics WHERE owner IN (%s,%s)',(owner,second))
            db.execute('DELETE FROM cloud_collections WHERE keyword=%s',(keyword,))
            db.execute('DELETE FROM cloud_registrations WHERE ip=%s',(ip,))
    print('PASS: browser ownership, PostgreSQL concurrency, daily/KST limit, edits/refresh/delete/re-add, failure/interruption, API auth/CORS and input validation')


if __name__=='__main__':main()
