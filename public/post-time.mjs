const KST = 9 * 3600000;
const DAY = 86400000;
const unknown = () => ({time:null,approximate:false,dayOnly:false});
const dayStart = time => Date.parse(new Date(time + KST).toISOString().slice(0,10) + 'T00:00:00+09:00');

function calendarTime(year, month, day, hour=0, minute=0, second=0) {
  const time = Date.UTC(year,month-1,day,hour,minute,second) - KST;
  const date = new Date(time + KST);
  return date.getUTCFullYear() === year && date.getUTCMonth()+1 === month && date.getUTCDate() === day && date.getUTCHours() === hour && date.getUTCMinutes() === minute && date.getUTCSeconds() === second ? time : null;
}

export function publication(post, observedAt=post.observedAt) {
  if (typeof post.published === 'string' && /^\d{4}-\d{2}-\d{2}(?:T|$)/.test(post.published)) {
    const dayOnly = !post.published.includes('T');
    const time = Date.parse(post.published + (dayOnly ? 'T00:00:00+09:00' : ''));
    const parts = post.published.slice(0,10).split('-').map(Number);
    if (Number.isFinite(time) && calendarTime(...parts) !== null) return {time,approximate:false,dayOnly};
  }
  const raw = String(post.publishedText || '').replace(/^작성시간\s*/, '').trim();
  let match = raw.match(/^(\d{4})[.\/-]\s*(\d{1,2})[.\/-]\s*(\d{1,2})\.?\s*(?:(\d{1,2}):(\d{2})(?::(\d{2}))?)?$/);
  if (match) {
    const time = calendarTime(+match[1],+match[2],+match[3],+(match[4] || 0),+(match[5] || 0),+(match[6] || 0));
    return time === null ? unknown() : {time,approximate:false,dayOnly:!match[4]};
  }
  const reference = Date.parse(post.observedAt || observedAt || '');
  // A saved relative label without its original collection time cannot be dated safely.
  if (!raw || !Number.isFinite(reference)) return unknown();
  const observed = new Date(reference + KST);
  const year = observed.getUTCFullYear(), month = observed.getUTCMonth()+1, day = observed.getUTCDate();
  const estimate = (time,dayOnly=false) => time === null ? unknown() : {time,approximate:true,dayOnly};
  if (/^(방금(?:\s*전)?|지금|just now|たった今)$/i.test(raw)) return estimate(reference);
  match = raw.match(/^(?:오늘|today|今日|어제|yesterday|昨日|그저께|一昨日)(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$/i);
  if (match) {
    const days = /^(그저께|一昨日)/.test(raw) ? 2 : /^(어제|yesterday|昨日)/i.test(raw) ? 1 : 0;
    const time = calendarTime(year,month,day,+(match[1] || 0),+(match[2] || 0),+(match[3] || 0));
    return estimate(time === null ? null : time - days*DAY,!match[1]);
  }
  match = raw.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
  if (match) {
    let time = calendarTime(year,month,day,+match[1],+match[2],+(match[3] || 0));
    if (time !== null && time > reference) time -= DAY;
    return estimate(time);
  }
  const plain = raw.replace(/[（(][^）)]*[）)]/g,'').trim();
  match = plain.match(/^(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日(?:\s+(\d{1,2}):(\d{2}))?$/) || plain.match(/^()(\d{1,2})[.\/](\d{1,2})\.?$/);
  if (match) {
    let time = calendarTime(+(match[1] || year),+match[2],+match[3],+(match[4] || 0),+(match[5] || 0));
    // ponytail: yearless labels use the latest past year; replace with source timestamps when available.
    if (!match[1] && time !== null && time > reference) time = calendarTime(year-1,+match[2],+match[3],+(match[4] || 0),+(match[5] || 0));
    return estimate(time,!match[4]);
  }
  const age = raw.replace(/^(?:스트리밍 시간:|최초 공개:|Streamed|Premiered)\s*/i,'');
  match = age.match(/^(\d+)\s*(초|분|시간|일|주|개월|달|년)\s*전$/) || age.match(/^(\d+)\s*(秒|分|時間|日|週間|ヶ月|か月|年)前$/) || age.match(/^(\d+)\s*(seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago$/i);
  if (!match && post.source === 'blind') match = age.match(/^(\d+)\s*(분|시간|일|주|개월|년)$/);
  if (!match) return unknown();
  const count = Number(match[1]), unit = match[2].toLowerCase().replace(/s$/,'');
  const units = [['초','秒','second'],['분','分','minute'],['시간','時間','hour'],['일','日','day'],['주','週間','week'],['개월','달','ヶ月','か月','month'],['년','年','year']];
  const index = units.findIndex(names => names.includes(unit));
  if (index < 0 || !Number.isSafeInteger(count) || count > 10000) return unknown();
  if (index < 5) {
    const time = reference - count * [1000,60000,3600000,DAY,7*DAY][index];
    return estimate(index >= 3 ? dayStart(time) : time,index >= 3);
  }
  const months = count * (index === 6 ? 12 : 1);
  const targetMonth = observed.getUTCMonth() - months;
  const lastDay = new Date(Date.UTC(year,targetMonth+1,0)).getUTCDate();
  const shifted = new Date(Date.UTC(year,targetMonth,Math.min(day,lastDay)));
  return estimate(shifted.getTime()-KST,true);
}

export function compareNewest(a,b) {
  const left = a.dateInfo.time, right = b.dateInfo.time;
  if (left === null) return right === null ? 0 : 1;
  if (right === null) return -1;
  return right-left || Number(a.dateInfo.dayOnly)-Number(b.dateInfo.dayOnly);
}
