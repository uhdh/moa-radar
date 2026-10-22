// Run: node check_dates.mjs (no packages or network).
import assert from 'node:assert/strict';
import {publication,compareNewest} from './public/post-time.mjs';

const reference = '2026-10-22T13:34:51+09:00';
const parsed = (text, source='youtube', at=reference) => publication({source,publishedText:text},at);
const iso = info => new Date(info.time).toISOString();
assert.equal(iso(parsed('6시간 전')), '2026-10-21T22:34:51.000Z');
assert.equal(iso(parsed('스트리밍 시간: 16시간 전')), '2026-10-21T12:34:51.000Z');
assert.equal(iso(parsed('3 days ago')), '2026-10-18T15:00:00.000Z');
assert.equal(iso(parsed('1주 전')), '2026-10-14T15:00:00.000Z');
assert.equal(iso(parsed('1개월 전')), '2026-09-21T15:00:00.000Z');
assert.equal(iso(parsed('1개월 전','blog','2026-03-31T12:00:00+09:00')), '2026-02-27T15:00:00.000Z');
assert.equal(iso(parsed('昨日 18:28','x')), '2026-10-21T09:28:00.000Z');
assert.equal(iso(parsed('10月19日(月) 22:27','x')), '2026-10-19T13:27:00.000Z');
assert.equal(iso(parsed('12月31日(水) 23:30','x','2026-01-01T01:00:00+09:00')), '2025-12-31T14:30:00.000Z');
assert.equal(iso(parsed('09:33:31','mlbpark')), '2026-10-22T00:33:31.000Z');
assert.equal(iso(parsed('23:59:00','mlbpark','2026-10-22T00:05:00+09:00')), '2026-10-21T14:59:00.000Z');
assert.equal(iso(parsed('작성시간 10.06','blind')), '2026-10-05T15:00:00.000Z');
assert.equal(iso(parsed('작성시간 5일','blind')), '2026-10-16T15:00:00.000Z');
assert.equal(iso(parsed('2026.10.21.','blog')), '2026-10-20T15:00:00.000Z');
assert.equal(iso(publication({published:'2026-10-22'})), '2026-10-21T15:00:00.000Z');
assert.equal(parsed('6시간 전').approximate, true);
assert.equal(publication({published:'2026-10-22'}).dayOnly, true);
assert.equal(publication({published:'2026-10-22T10:00:00+09:00'}).approximate, false);
assert.equal(publication({published:'2026-02-30'}).time,null);
for (const text of ['검색 날짜','내일','잘못된 시각','99:88','2026.13.40','10月99日(月)']) assert.equal(parsed(text).time,null,text);
assert.equal(parsed('3일 전','blog','').time,null,'Do not invent a date for old bookmarks without observation time');
const items = [
  {title:'unknown',publishedText:''},
  {title:'yesterday',publishedText:'昨日 18:28',source:'x'},
  {title:'old',published:'2014-12-26T19:54:00+09:00'},
  {title:'relative',publishedText:'2시간 전'},
  {title:'day',published:'2026-10-22'},
  {title:'new',published:'2026-10-22T13:30:00+09:00'},
].map(post => ({...post,dateInfo:publication(post,reference)}));
assert.deepEqual(items.sort(compareNewest).map(p=>p.title), ['new','relative','day','yesterday','old','unknown']);
assert(compareNewest({dateInfo:publication({published:'2026-10-22T00:00:00+09:00'})},{dateInfo:publication({published:'2026-10-22'})}) < 0,'Midnight with a known time precedes date-only posts');
const saved = {source:'youtube',publishedText:'2시간 전',observedAt:reference};
assert.deepEqual(publication(saved),publication(saved,'2026-10-23T23:59:00+09:00'),'Saved relative times stay anchored to collection time');
console.log('PASS: mixed-source newest order, KST date-only, relative labels, X dates, month/year rollovers, unknown dates, stable saved results');
