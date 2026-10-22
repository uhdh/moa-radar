"""Run `python check.py`; add --live to verify current community responses."""
from datetime import datetime
import json
import sys
import threading
from urllib.request import urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from server import CACHE, KST, Handler, SOURCES, ThreadingHTTPServer, clean_url, collect, is_post_url, number, parse_index, parse_posts, parse_social_index, post_date


def main():
    now = datetime(2026, 10, 22, 13, 30, tzinfo=KST)
    assert post_date('12:00', now) == '2026-10-22T12:00:00+09:00'
    assert post_date('2026.10.21') == '2026-10-21'
    assert post_date('알 수 없음') is None
    assert post_date('26.09.22 14:53') == '2026-09-22T14:53:00+09:00'
    assert post_date('26. 10. 14') == '2026-10-14'
    assert post_date('2026.10.07.') == '2026-10-07'
    assert post_date('5일 전') is None
    assert number('23K') == 23000 and number('1.2만') == 12000
    assert len(SOURCES) == 19 and 'news' not in SOURCES
    assert clean_url('dc', 'https://gall.dcinside.com/', 'javascript:alert(1)') is None
    assert clean_url('dc', 'https://gall.dcinside.com/', 'https://dcinside.com.evil.test/post') is None
    assert clean_url('clien', 'https://www.clien.net/', '/service/board/park/123?q=tracking#reply') == 'https://www.clien.net/service/board/park/123'
    assert clean_url('youtube', '', 'https://www.youtube.com/watch?v=abcdefghijk&utm_source=test') == 'https://www.youtube.com/watch?v=abcdefghijk'
    assert clean_url('bobaedream', '', 'https://www.bobaedream.co.kr/view?code=freeb&No=123&cpage=1') == 'https://www.bobaedream.co.kr/view?code=freeb&No=123'
    assert clean_url('mlbpark', '', 'https://mlbpark.donga.com/mp/b.php?b=bullpen&m=view&id=123&p=1') == 'https://mlbpark.donga.com/mp/b.php?b=bullpen&m=view&id=123'
    assert not is_post_url('instagram', 'https://www.instagram.com/steam/')
    assert not is_post_url('facebook', 'https://www.facebook.com/Steam')
    assert is_post_url('instagram', 'https://www.instagram.com/p/Abc123/')
    assert is_post_url('facebook', 'https://www.facebook.com/example/posts/123')
    assert not is_post_url('blog', 'https://blog.naver.com/account')
    index_fixture = '<div class="fds-web-doc-root"><a href="https://www.ppomppu.co.kr/zboard/view.php?id=freeboard&amp;no=123"><span class="sds-comps-text-type-headline1">스팀 이야기</span></a><a href="https://www.ppomppu.co.kr/zboard/view.php?id=freeboard&amp;no=123">실제 검색 요약</a></div>'
    indexed = parse_index('ppomppu', index_fixture)
    assert len(indexed) == 1 and indexed[0]['published'] is None
    assert indexed[0]['discovery'] == 'indexed' and indexed[0]['snippet'] == '실제 검색 요약'
    assert parse_index('instagram', '<div class="fds-web-doc-root"><a href="https://www.instagram.com/steam/"><span class="sds-comps-text-type-headline1">스팀</span></a></div>') == []
    assert clean_url('x', '', 'https://twitter.com/example/status/123/photo/1?s=20&id=tracking') == 'https://x.com/example/status/123'
    assert clean_url('threads', '', 'https://www.threads.net/%40example/post/Abc123/media?id=tracking') == 'https://www.threads.com/@example/post/Abc123'
    assert not is_post_url('x', 'https://x.com/example')
    assert not is_post_url('threads', 'https://www.threads.com/@example')
    social_samples = {
        'x': '<div class="Tweet_bodyContainer__test"><p class="Tweet_body__test">스팀 이야기</p><span class="Tweet_authorID__test">@example</span><time><a href="https://x.com/example/status/123?utm_source=test" data-cl-params="reply:12;">昨日 18:28</a></time></div>',
        'threads': '<div id="web"><ol><li><a href="https://www.threads.net/@example/post/Abc123/media">스팀 이야기</a><div><span class="util-Text--sub">2026/10/21</span> 실제 검색 요약</div></li><li><a href="https://www.threads.com/@example/post/Abc123/title">스팀 이야기</a></li><li><a href="https://www.threads.com/@example">스팀 계정</a></li><li><a href="https://www.threads.com/@example/post/Other">다른 이야기</a></li></ol></div>',
    }
    for source, sample in social_samples.items():
        social_posts = parse_social_index(source, sample, '스팀')
        assert len(social_posts) == 1 and social_posts[0]['title'] == '스팀 이야기', social_posts
        assert social_posts[0]['published'] is None and social_posts[0]['discovery'] == 'indexed'
        assert parse_social_index(source, sample, '없는검색어') == []
        with patch('server.fetch_html', return_value=sample) as fetch:
            result = collect(source, '스팀')
            assert result['status'] == 'ok' and len(result['posts']) == 1
            assert fetch.call_count == (1 if source == 'x' else 2)
    assert social_posts[0]['snippet'] == '실제 검색 요약' and social_posts[0]['publishedText'] == ''
    assert parse_social_index('x', social_samples['x'], '스팀')[0]['comments'] == 12
    CACHE.clear()
    samples = {
        'dc': '<ul class="sch_result_list"><li><a class="tit_txt" href="https://gall.dcinside.com/board/view/?id=test&amp;no=1">스<b>팀</b> 이야기</a><p class="link_dsc_txt">내용</p><span class="date_time">2026.10.22 12:01</span></li></ul>',
        'clien': '<div class="list_item"><a class="subject_fixed" href="/service/board/park/1">스팀 이야기</a><div class="preview">내용</div><span class="timestamp">2026-10-22 12:01:00</span><a class="list_reply">12</a><div class="list_hit"><span class="hit">1,234</span></div></div>',
        'ruliweb': '<table><tr class="table_body notice"><td><a class="subject_link" href="/community/board/300143/read/2">공지</a></td></tr><tr class="table_body other"><td><a class="subject_link" href="/other/read/3">추천</a></td></tr><tr class="table_body"><td><a class="subject_link" href="/community/board/300143/read/1">스팀 이야기 <span class="num_reply">(12)</span></a></td><td class="time">2026.10.22</td></tr></table>',
        'fmkorea': '<ul><li class="li"><h3 class="title"><a href="/123"><span class="ellipsis-target">스팀 이야기</span><span class="comment_count">[12]</span></a></h3><span class="regdate">2026.10.22</span></li></ul>',
    }
    for source, sample in samples.items():
        posts = parse_posts(source, sample, 'https://' + SOURCES[source]['domain'])
        assert len(posts) == 1, source
        assert posts[0]['title'] == '스팀 이야기', posts[0]
        assert posts[0]['published'], source
        assert posts[0]['comments'] == (None if source == 'dc' else 12), source
    extra_samples = {
        'mlbpark': '<table class="tbl_type01"><tbody><tr><td class="tit"><a class="txt" href="/mp/b.php?b=bullpen&amp;m=view&amp;id=123">스팀 이야기</a></td><td class="date">2026-10-21</td><td class="replycnt">12</td></tr></tbody></table>',
        'natepan': '<div class="srch_list"><ul class="s_list"><li><a class="subject" href="/talk/123">스팀 이야기</a><span class="date">26.10.21 12:00</span><span class="reple-num">12</span></li></ul></div>',
        'dogdrip': '<ul><li class="webzine"><h5 class="title"><a class="title-link" href="/dogdrip/123">스팀 이야기</a><span>12</span></h5></li></ul>',
        'blind': '<div class="article-list-pre"><div class="tit"><h3><a href="/kr/post/steam-AbCd">스팀 이야기</a></h3></div><span class="past">2026.10.21.</span><span class="cmt">12</span><span class="pv">23K</span></div>',
        'bobaedream': '<div class="search_Community"><ul><li><dt><a href="/view?code=freeb&amp;No=123">스팀 이야기</a></dt><div class="path"><span class="first">자유게시판</span><span class="next">26. 10. 21</span></div></li></ul></div>',
        'blog': '<div data-template-id="ugcItem"><a href="https://blog.naver.com/example/123"><span class="sds-comps-text-type-headline1">스팀 이야기</span></a><span class="sds-comps-profile-info-subtext">3일 전</span></div>',
        'cafe': '<div class="view_wrap"><a class="title_link" href="https://cafe.naver.com/example/123">스팀 이야기</a><span class="sub">2026.10.21.</span></div>',
        'youtube': '<script>var ytInitialData = {"contents":{"videoRenderer":{"videoId":"abcdefghijk","title":{"runs":[{"text":"스팀 이야기"}]},"publishedTimeText":{"simpleText":"3일 전"}}}};</script>',
    }
    for source, sample in extra_samples.items():
        posts = parse_posts(source, sample, 'https://' + SOURCES[source]['domain'])
        assert len(posts) == 1 and posts[0]['title'] == '스팀 이야기', (source, posts)
        assert is_post_url(source, posts[0]['url']), posts[0]
        if source in ('youtube', 'blog', 'dogdrip'):
            assert posts[0]['published'] is None
        else:
            assert posts[0]['published'], source
        if source == 'blind':
            assert posts[0]['views'] == 23000
    with patch('server.fetch_html', return_value=extra_samples['youtube']):
        assert collect('youtube', '무관한검색어')['posts'] == []
        assert len(collect('youtube', '스팀')['posts']) == 1
    CACHE.clear()
    assert parse_posts('clien', '<html>잠시 후 다시 시도하세요</html>', 'https://www.clien.net') == []
    with patch('server.urlopen', side_effect=HTTPError('https://www.fmkorea.com', 430, 'blocked', {}, None)):
        blocked = collect('fmkorea', 'check-blocked-response')
        assert blocked['status'] == 'error' and blocked['posts'] == []
        assert blocked['message']

    # Same API request twice must not mutate cached source results.
    for source in SOURCES:
        import time
        CACHE[(source, 'self-check')] = (time.monotonic(), {
            'source': source, 'status': 'ok', 'posts': parse_posts(source, samples[source], 'https://' + SOURCES[source]['domain']) if source in samples else [],
            'searchUrl': 'https://' + SOURCES[source]['domain'], 'cached': False,
        })
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{httpd.server_port}'
    try:
        for _ in range(2):
            with urlopen(base + '/api/search?q=self-check') as response:
                result = json.load(response)
            assert len(result['posts']) == 4
            assert len(result['sources']) == 19 and all(s['cached'] for s in result['sources'])
            assert all('posts' not in s for s in result['sources'])
        try:
            urlopen(base + '/api/search?q=')
            raise AssertionError('Empty search must be rejected')
        except HTTPError as exc:
            assert exc.code == 400
        if '--live' in sys.argv:
            from urllib.parse import quote
            with urlopen(base + '/api/search?q=' + quote('스팀'), timeout=40) as response:
                result = json.load(response)
            assert result['posts'], 'No live posts returned'
            for status in result['sources']:
                count = sum(p['source'] == status['source'] for p in result['posts'])
                print(f"LIVE {status['source']}: {status['status']} / {count} posts")
                assert status['status'] in ('ok', 'error', 'unavailable'), status
                if status['status'] != 'ok':
                    assert count == 0 and status['message'], status
            assert len(result['sources']) == 19
            assert sum(s['status'] == 'ok' for s in result['sources']) >= 8, result['sources']
    finally:
        httpd.shutdown()
        httpd.server_close()
    print('PASS: 19 sources, X/Threads collectors, dates, identity queries, indexed posts, profile exclusion, access restriction, cached repeat search')


if __name__ == '__main__':
    main()
