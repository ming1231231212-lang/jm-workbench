/* Exact root/path extraction. Never recursively collect arbitrary photo objects. */
const extract = (() => {
  const fail = message => { throw new Error(message); };
  const cache = state => state?.defaultClient || state || {};
  const deref = (st, value) => value?.__ref ? st[value.__ref] : value?.type === 'id' ? st[value.id] : value?.type === 'json' ? value.json : value;
  const operation = (st, name, parameter, expected) => {
    const matches = Object.entries(st.ROOT_QUERY || {}).filter(([key]) => {
      if (!key.startsWith(name + '(') || !key.endsWith(')')) return false;
      try { return JSON.parse(key.slice(name.length + 1, -1))[parameter] === expected; }
      catch { return false; }
    });
    if (matches.length !== 1) fail('EXACT_OPERATION_NOT_FOUND');
    return { key: matches[0][0], value: deref(st, matches[0][1]) };
  };
  const site = url => {
    const u = new URL(url);
    if (u.protocol !== 'https:' || u.hostname !== 'www.kuaishou.com') fail('WRONG_SITE');
    return u;
  };
  const slimFeed = (f, st) => {
    f = deref(st, f);
    const photo = deref(st, f?.photo), author = deref(st, f?.author);
    if (!photo?.id || !author?.id) fail('MISSING_VIDEO_AUTHOR');
    return {video_id: String(photo.id), author_id: String(author.id), caption: photo.caption || '',
      nickname: author.name || '', can_comment: f.canAddComment === true || f.canAddComment === 1};
  };
  function search(init, apollo, url, keyword) {
    const u = site(url);
    if (u.pathname !== '/search/video' || u.searchParams.get('searchKey') !== keyword) fail('WRONG_QUERY_PAGE');
    if (!keyword || keyword.length > 40 || /[.\r\n]/.test(keyword)) fail('INVALID_KEYWORD');
    // Current Kuaishou SSR cache uses shifted cache keys. Match the complete keyword segment.
    const shifted = [...keyword].map(c => String.fromCodePoint(c.codePointAt(0) + 2)).join('');
    const prefix = 'tusjoh.0sftu0w0tfbsdi0gffe-pckfdu.lfzxpse.uvtkpi\\u002F' + shifted + '.qbhf.';
    const entries = Object.entries(init || {}).filter(([k]) => k.startsWith(prefix));
    let found, st = {}, source;
    if (entries.length === 1) {
      found = entries[0][1]; source = 'INIT_STATE[' + entries[0][0] + '].feeds';
    } else if (entries.length > 1) fail('AMBIGUOUS_SEARCH');
    else {
      st = cache(apollo);
      const match = operation(st, 'visionSearchPhoto', 'keyword', keyword);
      found = match.value; source = 'ROOT_QUERY.' + match.key + '.feeds';
    }
    if (found?.result !== 1 || !Array.isArray(found.feeds)) fail('SEARCH_RESULT_NOT_SUCCESS');
    return {source_path: source, keyword, rows: found.feeds.slice(0, 20).map(f => slimFeed(f, st))};
  }
  function detail(apollo, url, videoId) {
    const u = site(url);
    if (u.pathname !== '/short-video/' + videoId) fail('WRONG_VIDEO_PAGE');
    const st = cache(apollo), match = operation(st, 'visionVideoDetail', 'photoId', videoId);
    const d = match.value;
    if (d?.status !== 1) fail('VIDEO_UNAVAILABLE');
    const row = slimFeed(d, st);
    if (row.video_id !== videoId) fail('VIDEO_ID_MISMATCH');
    const limit = deref(st, d.commentLimit);
    // Official short-video.4caa6fda.js: 0 => normal input, 1 => disabled/friends-only.
    // Do not default missing values to 0 as the UI does; unknown values fail closed.
    row.comment_permission_code = limit?.canAddComment ?? null;
    row.can_comment = limit?.canAddComment === 0;
    return {...row, source_path: 'ROOT_QUERY.' + match.key, detail_verified: true};
  }
  function account(init, apollo) {
    const profile = init?.['tusjoh.0sftu0w0qspgjmf0hfu-pckfdu.'];
    if (profile?.result === 1 && profile.eid) return {id: String(profile.eid), name: profile.userName || ''};
    const st = cache(apollo), user = deref(st, st.ROOT_QUERY?.userInfo);
    if (user?.id) return {id: String(user.eid || user.id), name: user.name || ''};
    fail('LOGIN_NOT_VERIFIED');
  }
  return { search, detail, account };
})();
if (typeof module !== 'undefined') module.exports = extract;
