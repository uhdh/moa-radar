// Run: node check_keyword.mjs (no packages or network).
import assert from 'node:assert/strict';
import {exactMatch,matchesExact} from './public/keyword-match.mjs';

for (const text of ['스팀','스팀 할인 소식','오늘 스팀 할인','#스팀','(스팀)','스팀!','게임:스팀/뉴스']) {
  assert(matchesExact({title:text},'스팀'),text);
}
for (const text of ['스팀덱','스팀은','슈퍼스팀','스팀2','스팀_덱','Steam','게임 소식']) {
  assert(!matchesExact({title:text},'스팀'),text);
}
assert(matchesExact({title:'다른 제목',snippet:'스팀 할인 소식'},'스팀'));
assert(!matchesExact({title:'스팀',snippet:'덱'},'스팀 덱'),'Do not join the title and snippet into a phrase');
assert(matchesExact({title:'스팀  덱 소식'},' 스팀 덱 '));
assert(matchesExact({title:'STEAM sale'},'Steam'));
assert(!matchesExact({title:'steamdeck'},'Steam'));
assert(matchesExact({title:'C++ 질문'},'C++'));
assert(!matchesExact({title:'C++언어'},'C++'));
assert(!matchesExact({title:'aaa'},'.*'),'Keyword text must not execute as a regular expression');
assert(matchesExact({title:'(a+b) 소식'},'(a+b)'));
assert(matchesExact({title:'스팀 할인'},'스팀'),'Composed and decomposed Korean should agree');
assert(!matchesExact({title:'스팀'},'  '));
assert.deepEqual(exactMatch('스팀덱 할인, 스팀 정품','스팀'),{index:8,value:'스팀'});
assert.deepEqual(exactMatch('오늘 스팀  덱 소식','스팀 덱'),{index:3,value:'스팀  덱'});
console.log('PASS: exact Korean words, attached suffixes, hashtags, phrase boundaries, case, punctuation and regex escaping');
