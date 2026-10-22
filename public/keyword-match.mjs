// Word boundaries include Korean and other Unicode letters, unlike JavaScript's ASCII \b.
export function exactMatch(value, keyword) {
  const text = String(value || '').normalize('NFC');
  const word = String(keyword || '').normalize('NFC').trim();
  if (!word) return null;
  const literal = word.split(/\s+/).map(part => part.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('\\s+');
  const pattern = new RegExp(`(^|[^\\p{L}\\p{M}\\p{N}_])(${literal})(?=$|[^\\p{L}\\p{M}\\p{N}_])`,'iu');
  const match = pattern.exec(text);
  return match ? {index:match.index+match[1].length,value:match[2]} : null;
}

export function matchesExact(post, keyword) {
  return [post.title,post.snippet].some(value => exactMatch(value,keyword) !== null);
}
