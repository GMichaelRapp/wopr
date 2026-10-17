// OSINT Citation Generator formatter (the <script id="core"> block of
// https://gmichaelrapp.github.io/OSINT_Cites/). MIT License, (c) 2026 G. Michael Rapp.
// Fallback copy: build.py fetches the current version from the generator on each run.
var OSINT = (function () {
  'use strict';
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  var REL = { A: 'Highly Reliable', B: 'Usually Reliable', C: 'Fairly Reliable', D: 'Not Usually Reliable', E: 'Unreliable', F: 'Unknown' };
  var CRED = { 1: 'Confirmed', 2: 'Probable', 3: 'Possible', 4: 'Doubtful', 5: 'Improbable', 6: 'Unknown' };
  var ZROWS = ['GGGYYX', 'GGYYOX', 'YYYOOX', 'OOOORX', 'RRRRRX', 'XXXXXX'];
  var ZNAME = { G: 'Green', Y: 'Yellow', O: 'Orange', R: 'Red', X: 'Gray' };
  var HANDLING = {
    G: 'May be used as core evidence.',
    Y: 'Usable with framing and corroboration. Say in the text that the claim is not confirmed.',
    O: 'Weak. Use only where necessary, with the caveat stated in a footnote.',
    R: 'Likely misleading or false. Cite only to identify and challenge the claim, never to support one.',
    X: 'Unverifiable. May show that a claim is circulating; may never be the sole support for a judgment.'
  };
  var SHORTENERS = ['bit.ly', 'tinyurl.com', 't.co', 'goo.gl', 'ow.ly', 'buff.ly', 'is.gd', 'lnkd.in', 'shorturl.at', 'rb.gy', 'tiny.cc', 'cutt.ly', 'trib.al', 'dlvr.it'];
  var VOLATILE = ['x.com', 'twitter.com', 't.me', 'telegram.me', 'discord.com', 'discord.gg', 'facebook.com', 'instagram.com', 'tiktok.com', 'reddit.com', 'bsky.app', 'threads.net', 'vk.com', 'weibo.com', 'truthsocial.com', 'mastodon.social', 'medium.com', 'blogspot.com', 'wordpress.com'];
  var ORG = /\b(Staff|Department|Ministry|Institute|Institution|University|Corporation|Council|Bureau|Service|Office|Agency|Labs?|PBC|Inc|LLC|Ltd|News|Organization|Bank|Fund|Union|Commission|Court|House|Congress|Parliament|Foundation|Center|Centre|Nations|Reserve|Government|Press|Group|Project|Analysts|Endowment|Command|Force|Navy|Army|accounts)\b/i;

  function straight(s) { return String(s == null ? '' : s).replace(/[“”]/g, '"').replace(/[‘’]/g, "'"); }
  function clean(s) { return straight(s).replace(/\s+/g, ' ').trim(); }
  function lines(s) { return String(s == null ? '' : s).split(/[\n;]+/).map(clean).filter(Boolean); }
  function listJoin(a) {
    if (a.length <= 1) return a[0] || '';
    if (a.length === 2) return a[0] + ' and ' + a[1];
    return a.slice(0, -1).join(', ') + ', and ' + a[a.length - 1];
  }
  function authorBlock(a) { return a.length >= 4 ? a.slice(0, 3).join(', ') + ', et al.' : listJoin(a); }
  var ROLE_TAG = /\s*\((eds?|trans|contr)\.\)$/i;
  // Editors, translators and contributors each have their own field. Lists saved before 3.1 kept
  // all three in one box (st.contribs), tagged by hand or given one default role; those still read correctly.
  function splitPeople(st) {
    var out = { ed: lines(st.editors), trans: lines(st.translators), contr: lines(st.contributors) };
    lines(st.contribs).forEach(function (n) {
      var m = n.match(ROLE_TAG), role = m ? m[1].toLowerCase().replace('eds', 'ed') : (st.contribRole || 'ed');
      (out[role] || out.ed).push(n);
    });
    function tidy(a) { return a.map(function (n) { return n.replace(ROLE_TAG, ''); }).filter(Boolean); }
    return { ed: tidy(out.ed), trans: tidy(out.trans), contr: tidy(out.contr) };
  }
  function roleList(st) {
    var p = splitPeople(st);
    return p.ed.map(function (n) { return n + ' (ed.)'; })
      .concat(p.trans.map(function (n) { return n + ' (trans.)'; }), p.contr.map(function (n) { return n + ' (contr.)'; }));
  }
  // 'en': in English. 'foreign': in another language. 'published': an English translation someone published.
  function langModeOf(st) {
    if (st.langMode === 'en' || st.langMode === 'foreign' || st.langMode === 'published') return st.langMode;
    return (clean(st.transTitle) || clean(st.origLang) || st.transBy) ? 'foreign' : 'en';
  }
  // Bring a source saved by an earlier version up to the current fields.
  function upgradeState(st) {
    var out = {}, k, p = splitPeople(st);
    for (k in st) if (Object.prototype.hasOwnProperty.call(st, k) && k !== 'contribs' && k !== 'contribRole') out[k] = st[k];
    out.editors = p.ed.join('\n'); out.translators = p.trans.join('\n'); out.contributors = p.contr.join('\n');
    out.langMode = langModeOf(st);
    return out;
  }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function monthIndex(name) {
    var n = String(name).toLowerCase().replace(/\.$/, '');
    if (n.length < 3) return -1;
    for (var i = 0; i < 12; i++) if (MONTHS[i].toLowerCase().indexOf(n) === 0) return i;
    return -1;
  }
  function normDate(raw) {
    var s = clean(raw), m, mi, d;
    if (!s) return { text: '', level: 'none' };
    if (/^n\.?\s?d\.?$/i.test(s)) return { text: 'n.d.', level: 'none' };
    if (/^\d{4}$/.test(s)) return { text: s, level: 'year' };
    function full(y, mo, da) {
      mo = +mo; da = +da;
      if (mo < 1 || mo > 12 || da < 1 || da > 31) return { text: s, level: 'raw' };
      return { text: pad2(da) + ' ' + MONTHS[mo - 1] + ' ' + y, level: 'day' };
    }
    if ((m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/))) return full(m[1], m[2], m[3]);
    if ((m = s.match(/^(\d{4})-(\d{1,2})$/)) && +m[2] >= 1 && +m[2] <= 12) return { text: MONTHS[+m[2] - 1] + ' ' + m[1], level: 'month' };
    if ((m = s.match(/^(\d{1,2})[\/.](\d{1,2})[\/.](\d{4})$/))) {
      return (+m[1] > 12 && +m[2] <= 12) ? full(m[3], m[2], m[1]) : full(m[3], m[1], m[2]);
    }
    if ((m = s.match(/^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})$/)) && (mi = monthIndex(m[2])) >= 0) return full(m[3], mi + 1, m[1]);
    if ((m = s.match(/^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$/)) && (mi = monthIndex(m[1])) >= 0) return full(m[3], mi + 1, m[2]);
    if ((m = s.match(/^([A-Za-z]{3,9})\.?,?\s+(\d{4})$/)) && (mi = monthIndex(m[1])) >= 0) return { text: MONTHS[mi] + ' ' + m[2], level: 'month' };
    return { text: s, level: 'raw' };
  }
  function normLocator(raw) {
    var s = clean(raw).replace(/\.$/, ''), m, body;
    if (!s) return '';
    var PAGES = /^[\divxlcdm\s,–—-]+$/i;
    body = s;
    if ((m = s.match(/^pp?\.?\s*(.+)$/i)) && PAGES.test(m[1])) body = m[1];
    if (PAGES.test(body) && /[\divxlcdm]/i.test(body)) {
      var p = body.replace(/\s*[-–—]\s*/g, '–').replace(/\s*,\s*/g, ', ');
      return (/[–,]/.test(p) ? 'pp. ' : 'p. ') + p;
    }
    return s.replace(/(\d)\s*[-–—]\s*(?=\d)/g, '$1–');
  }
  function hostOf(u) {
    var m = String(u).match(/^[a-z]+:\/\/([^\/?#:]+)/i);
    return m ? m[1].toLowerCase().replace(/^www\./, '') : '';
  }
  function hostIn(h, list) {
    for (var i = 0; i < list.length; i++) if (h === list[i] || h.slice(-(list[i].length + 1)) === '.' + list[i]) return true;
    return false;
  }
  function normUrl(raw) {
    var s = String(raw == null ? '' : raw).trim(), doi = false;
    if (!s) return { url: '', doi: false };
    s = s.replace(/^doi:\s*/i, '');
    if (/^10\.\d{4,9}\/\S+$/.test(s)) return { url: 'https://doi.org/' + s, doi: true };
    if (/^(https?:\/\/)?(dx\.)?doi\.org\//i.test(s)) {
      var fixed = 'https://doi.org/' + s.replace(/^(https?:\/\/)?(dx\.)?doi\.org\//i, '');
      return { url: fixed, doi: fixed !== s };
    }
    if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s) && /^[\w-]+(\.[\w-]+)+(\/|$|\?|#)/.test(s)) s = 'https://' + s;
    return { url: s, doi: doi };
  }
  function cleanTitle(raw, style) {
    var s = clean(raw), m = s.match(/^"(.*)"$/);
    if (m && m[1].indexOf('"') === -1) s = m[1];
    s = s.replace(/,$/, '');
    if (style === 'quotes') s = s.replace(/"/g, "'");
    return s;
  }
  function zoneOf(r) {
    if (!/^[A-F][1-6]$/.test(r || '')) return '';
    return ZROWS[+r[1] - 1]['ABCDEF'.indexOf(r[0])];
  }
  function words(s) { return s ? s.split(/\s+/).filter(Boolean).length : 0; }
  function surname(n) {
    var w = n.split(' ');
    if (w.length > 3 || w.length < 2 || /\d/.test(n) || ORG.test(n)) return n;
    return w[w.length - 1];
  }
  function deriveName(authors) {
    var s = authors.map(surname);
    if (s.length >= 4) return s[0] + ' et al.';
    return listJoin(s);
  }
  function deriveShortTitle(t) {
    var q = t.match(/^(.+?[?!])\s/);
    if (q) return q[1];
    var i = t.indexOf(':');
    return (i > 0 ? t.slice(0, i) : t).trim();
  }

  function accessOf(st) {
    var raw = Array.isArray(st.access) ? st.access : (st.access ? [st.access] : []);
    var out = [];
    raw.forEach(function (a) {
      var v = a === 'other' ? clean(st.accessNote) : clean(a);
      if (v && out.indexOf(v) === -1) out.push(v);
    });
    return out;
  }
  function has(list, x) { return list.indexOf(x) !== -1; }
  var REVIEW_Q = ['peer-reviewed', 'editor-reviewed', 'student-edited', 'not peer-reviewed', 'review status unclear'];
  var UNI_PRESS = /\buniversity press\b/i;
  var TRADE_HOUSE = /\b(penguin|random house|harpercollins|simon (&|and) schuster|hachette|knopf|doubleday|farrar, straus|norton|basic books|publicaffairs|little, brown|viking|scribner|st\. martin's|henry holt)\b/i;

  function build(st) {
    var seg = [], checks = [], slots = {};
    function push(s, i) { if (!s) return; var l = seg[seg.length - 1]; if (l && l.i === !!i) l.s += s; else seg.push({ s: s, i: !!i }); }
    function tail() { return seg.length ? seg[seg.length - 1].s.slice(-1) : ''; }
    function sp() { if (seg.length && tail() !== ' ') push(' '); }
    function add(level, msg) { checks.push({ level: level, msg: msg }); }

    var style = st.titleStyle || 'quotes';
    var authors = lines(st.authors), contribs = roleList(st), mode = langModeOf(st);
    var who = authorBlock(authors), cb = listJoin(contribs);
    if (who && cb) who += '; ' + cb; else if (cb) who = cb;
    var title = cleanTitle(st.title, style), trans = mode === 'foreign' ? cleanTitle(st.transTitle, style) : '';
    var rawLoc = clean(st.location), loc = rawLoc, locSame = false;
    if (loc && title && loc.toLowerCase() === title.toLowerCase()) { loc = ''; locSame = true; }

    var type = clean(st.descType), items = [];
    if (type) items.push(type);
    lines(st.descDetails).forEach(function (x) { items.push(x); });
    var quals = Array.isArray(st.quals) ? st.quals.map(clean).filter(Boolean) : [];
    quals.forEach(function (q) { items.push(q); });
    var lang = mode === 'en' ? '' : clean(st.origLang), transBy = mode === 'foreign' ? st.transBy : '';
    if (mode === 'published') { if (lang) items.push('translated from ' + lang); }
    else if (transBy === 'machine') { items.push('machine translation'); if (lang) items.push('original in ' + lang); }
    else { if (lang) items.push('original in ' + lang); if (transBy === 'own') items.push('translation by author'); }
    var accessList = accessOf(st);
    accessList.forEach(function (a) { items.push(a); });
    var access = accessList.length > 0;
    var descWords = words(items.join(' ').replace(/[;,]/g, ' '));
    var rating = /^[A-F][1-6]$/.test(st.rating || '') ? st.rating : '';
    if (rating) items.push(rating);

    var pub = clean(st.publisher), pubSame = false;
    if (pub && rawLoc && pub.toLowerCase() === rawLoc.toLowerCase()) { pub = ''; pubSame = true; }
    var d = normDate(st.date), acc = normDate(st.accessed);
    var u = normUrl(st.url), au = normUrl(st.archiveUrl), ad = normDate(st.archiveDate);
    var locator = normLocator(st.locator), note = clean(st.note), lead = clean(st.lead);

    var empty = !who && !title && !loc && !items.length && !pub && !d.text && !u.url && !locator;
    if (empty) return { seg: [], checks: [], slots: {}, empty: true, rating: '', zone: '' };

    if (lead) push(lead + ' ');
    if (who) { push(who); if (title || loc) push(', '); }
    var endP = /[?!]$/.test(title);
    if (title) {
      if (style === 'quotes') {
        if (trans) { push('"' + title + '" ["' + trans + '"]'); if (loc) push(', '); }
        else { push('"' + title + (loc && !endP ? ',' : '') + '"'); if (loc) push(' '); }
      } else if (style === 'italics') {
        push(title, true);
        if (trans) { push(' ['); push(trans, true); push(']'); }
        if (loc) push(endP && !trans ? ' ' : ', ');
      } else {
        push(title + (trans ? ' [' + trans + ']' : ''));
        if (loc) push(', ');
      }
    }
    if (loc) push(loc, true);
    if (items.length) { sp(); push('[' + items.join('; ') + ']'); }

    var dateText = d.text || 'n.d.';
    if ((st.dateKind === 'updated' || st.dateKind === 'captured') && d.text && d.text !== 'n.d.') dateText = st.dateKind + ' ' + dateText;
    if (acc.text) dateText += ', accessed ' + acc.text;
    sp(); push('(' + (pub ? pub + ': ' : '') + dateText + ')');
    if (u.url) { sp(); push(u.url); }
    if (locator) push(': ' + locator);
    if (!/[.?!]$/.test(tail()) || (u.url && !locator)) push('.');
    if (au.url) push(' Archived: ' + au.url + (ad.text ? ' (captured ' + ad.text + ')' : '') + '.');
    if (note) push(' ' + note + (/[.?!]$/.test(note) ? '' : '.'));

    slots.author = who ? 'filled' : 'dropped';
    slots.title = title ? 'filled' : 'missing';
    slots.location = loc ? 'filled' : 'dropped';
    slots.description = type ? 'filled' : 'missing';
    slots.publisher = pub ? 'filled' : 'dropped';
    slots.date = (d.text && d.text !== 'n.d.') ? 'filled' : 'nd';
    slots.url = u.url ? 'filled' : 'dropped';
    slots.locator = locator ? 'filled' : 'dropped';

    if (!title) add('fix', 'No title. Where a source has none, write a plain description in the title slot and set it as a plain description.');
    if (!type) add('fix', 'The description bracket is empty. It is the one slot that is never dropped.');
    if (st.ai && rating !== 'F6') add('check', 'AI model output is rated F6 by default.');
    var h = hostOf(u.url);
    if (h && hostIn(h, SHORTENERS)) add('fix', 'That is a link shortener. Give the full URL.');
    if (u.url && /[?&](utm_[a-z]+|fbclid|gclid|mc_cid|igshid)=/i.test(u.url)) add('check', 'The URL carries tracking parameters. Trim them so the link is the stable one.');
    if ((st.volatile || (h && hostIn(h, VOLATILE))) && !au.url) add('check', 'Volatile source with no archive link. Archive it now and add the link and capture date.');
    if (au.url && !ad.text) add('check', 'The archive link has no capture date.');
    if (st.live && !acc.text) add('check', 'A continuously updated source needs an access date.');
    if (st.dayDate && (d.level === 'year' || d.level === 'month')) add('check', 'This kind of source takes the full date: DD Month YYYY.');
    var z = zoneOf(rating);
    if (z && z !== 'G') add('check', rating + ' sits in the ' + ZNAME[z] + ' zone. ' + HANDLING[z]);
    if (rating === 'C1') add('note', 'C1 is the weakest of the Green blocks. Say so when leaning on it.');
    if (words(rawLoc) > 10 && st.type !== 'chapter') add('check', 'Location runs ' + words(rawLoc) + ' words. The guide asks for ten or fewer.');
    if (!who && title) add('note', 'No author, so the footnote opens with the title. Use the organization if there is one, or the outlet plus Staff.');
    if (authors.length >= 4) add('note', authors.length + ' authors: the first three are named, then et al.');
    if (locSame) add('note', 'Location repeats the title, so it is dropped.');
    if (pubSame) add('note', 'Publisher repeats the location, so it is dropped.');
    if (!d.text) add('note', 'No date given, so the parenthetical reads n.d. If you can establish one, put [ca. YYYY] in the description and say how.');
    if (d.level === 'raw') add('note', 'Date left as typed. House form is DD Month YYYY, or the year alone for books and journal articles.');
    if (u.doi) add('note', 'DOI rewritten in resolvable form.');
    if (descWords > 10) add('note', 'Description runs ' + descWords + ' words against a target of ten. Archival detail and imagery metadata often need the room.');
    if (/^(cited|quoted) in$/i.test(lead)) add('note', 'A secondary citation inherits the weaker of the two ratings and is never stronger than the intermediary.');
    if (mode === 'foreign' && !lang) add('check', 'This source is marked as not in English, but no language is given.');
    if (mode === 'foreign' && title && !trans) add('note', 'Add the title in English so a reader can tell what the source is.');
    if (mode === 'published' && !contribs.some(function (c) { return /\(trans\.\)$/.test(c); })) add('note', 'A published translation credits its translator. Add the name under Translators.');
    if (transBy === 'machine') add('note', 'Check any quotation against the original before it is used as a quotation.');
    if (access) add('note', 'Access is restricted, so some readers cannot check this source. Where a free version exists, such as a preprint or an official release, cite that instead or alongside.');
    var tl = type.toLowerCase();
    if (/unverified|suspected synthetic|suspected inauthentic|manipulated media|ai-generated/.test(tl) || has(quals, 'provenance unverified') || has(quals, 'suspected synthetic') || has(quals, 'AI-generated') || has(quals, 'digitally altered')) add('check', 'Unverified or synthetic material. Say in the commentary what was checked, what was not, and why it is cited at all.');
    if (has(quals, 'retracted')) add('check', 'Retracted work. Cite it only to discuss the retraction, and say so in the commentary.');
    if (/state media|party newspaper/.test(tl)) add('note', 'State or party media: evidence of official messaging first, of fact second.');
    if (/^leaked|captured document|leak site|hacktivist/.test(tl) || has(quals, 'leaked') || has(quals, 'captured')) add('note', 'Leaked or captured material. Say how its authenticity was established, and rate the information on its own merits.');
    if (/^(preprint paper|working paper)$/.test(tl) || has(quals, 'preprint') || has(quals, 'not peer-reviewed')) add('note', 'Not peer-reviewed. Say so in the text wherever the claim is load-bearing.');
    var rq = quals.filter(function (q) { return has(REVIEW_Q, q); });
    if (rq.length > 1) add('check', 'More than one review status is ticked (' + rq.join(', ') + '). Keep the one that fits.');
    if (tl === 'journal article' && !rq.length) add('check', 'Journal Article says nothing about review. Set the review status, or mark it review status unclear if the journal does not say.');
    if (tl === 'peer-reviewed article' && rq.some(function (q) { return q !== 'peer-reviewed'; })) add('check', 'The description says peer-reviewed and a qualifier says otherwise. Use Journal Article with the qualifier.');
    if (tl === 'peer-reviewed article' && rq.length === 1 && rq[0] === 'peer-reviewed') add('note', 'Peer-Reviewed Article already says it, so the peer-reviewed qualifier can go.');
    if (has(quals, 'review status unclear')) add('note', 'Review status not established. Treat the article as unreviewed until the journal\'s own statement says otherwise.');
    var rawPub = clean(st.publisher);
    if (tl === 'trade book' && UNI_PRESS.test(rawPub)) add('note', 'Trade Book from a university press. University presses publish both kinds. If it argues one thesis for specialists, with notes and a bibliography, Monograph fits better.');
    if (tl === 'monograph' && TRADE_HOUSE.test(rawPub)) add('note', 'Monograph from a commercial publisher. Books from trade houses are usually Trade Books, even when a scholar wrote them. Keep Monograph only if it is written for specialists.');
    if (st.type === 'social' && style !== 'plain' && words(title) > 15) add('note', 'The post title runs ' + words(title) + ' words. The opening words, about a dozen, are enough to identify the post. End with an ellipsis where you stop.');
    if (type && !LIB_INDEX[tl]) add('note', 'That description is not in the library. Fine if it fits in ten words; send a note so it can be added.');
    if (st.ai) add('note', 'Keep the prompt and transcript on file, and disclose the use in the piece itself as well as here.');
    if (!rating && !st.ai) add('note', 'No rating. Optional, but expected on any source a reader might question.');

    var order = { fix: 0, check: 1, note: 2 };
    checks.sort(function (a, b) { return order[a.level] - order[b.level]; });
    return { seg: seg, checks: checks, slots: slots, empty: false, rating: rating, zone: z };
  }

  function shortForms(st) {
    var style = st.titleStyle || 'quotes';
    var authors = lines(st.authors);
    var name = clean(st.shortName) || deriveName(authors);
    var full = cleanTitle(st.title, style);
    var t = cleanTitle(st.shortTitle, style) || deriveShortTitle(full);
    var useT = (st.shortUseTitle !== false || !name) && !!t;
    var L = normLocator(st.locator);
    var s = [], i = [];
    function push(x, it) { if (!x) return; var l = s[s.length - 1]; if (l && l.i === !!it) l.s += x; else s.push({ s: x, i: !!it }); }
    if (name) push(name);
    if (useT) {
      if (name) push(', ');
      if (style === 'quotes') {
        var endP = /[?!]$/.test(t);
        push('"' + t + (endP ? '' : (L ? ',' : '.')) + '"');
        if (L) push(' ' + L + '.');
      } else {
        push(t, style === 'italics');
        push(L ? ', ' + L + '.' : '.');
      }
    } else if (name) {
      push(L ? ', ' + L + '.' : (/\.$/.test(name) ? '' : '.'));
    }
    i.push({ s: 'Ibid.' + (L ? ', ' + L + '.' : ''), i: false });
    return { short: s, ibid: i, name: deriveName(authors), title: deriveShortTitle(full) };
  }

  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function toHTML(seg, mode) {
    var t = mode === 'u' ? 'u' : 'i';
    return seg.map(function (x) { return x.i ? '<' + t + '>' + esc(x.s) + '</' + t + '>' : esc(x.s); }).join('');
  }
  function toMarkdown(seg) { return seg.map(function (x) { return x.i ? '*' + x.s + '*' : x.s; }).join(''); }
  function toPlain(seg) { return seg.map(function (x) { return x.s; }).join(''); }
  function joinSources(list) {
    var out = [];
    list.forEach(function (seg, n) {
      var copy = seg.map(function (x) { return { s: x.s, i: x.i }; });
      if (copy.length && n < list.length - 1) copy[copy.length - 1].s = copy[copy.length - 1].s.replace(/\.$/, '');
      if (n > 0) out.push({ s: '; ', i: false });
      out = out.concat(copy);
    });
    return out;
  }

  // ---- list files and exports ----
  var CRC_T = null;
  function crc32(b) {
    var n, k, c, i, crc = 0xFFFFFFFF;
    if (!CRC_T) { CRC_T = []; for (n = 0; n < 256; n++) { c = n; for (k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1); CRC_T[n] = c >>> 0; } }
    for (i = 0; i < b.length; i++) crc = CRC_T[(crc ^ b[i]) & 0xFF] ^ (crc >>> 8);
    return (crc ^ 0xFFFFFFFF) >>> 0;
  }
  function utf8(s) { return new TextEncoder().encode(s); }
  function zipStore(files) {
    var parts = [], central = [], offset = 0, cdSize = 0, total = 0, pos = 0, out;
    function u16(n) { return [n & 255, (n >>> 8) & 255]; }
    function u32(n) { return [n & 255, (n >>> 8) & 255, (n >>> 16) & 255, (n >>> 24) & 255]; }
    files.forEach(function (f) {
      var name = utf8(f.name), crc = crc32(f.data), size = f.data.length;
      var local = [].concat(u32(0x04034b50), u16(20), u16(0x0800), u16(0), u16(0), u16(0x21), u32(crc), u32(size), u32(size), u16(name.length), u16(0));
      parts.push(new Uint8Array(local), name, f.data);
      central.push([new Uint8Array([].concat(u32(0x02014b50), u16(20), u16(20), u16(0x0800), u16(0), u16(0), u16(0x21), u32(crc), u32(size), u32(size), u16(name.length), u16(0), u16(0), u16(0), u16(0), u32(0), u32(offset))), name]);
      offset += local.length + name.length + size;
    });
    central.forEach(function (c) { parts.push(c[0], c[1]); cdSize += c[0].length + c[1].length; });
    parts.push(new Uint8Array([].concat(u32(0x06054b50), u16(0), u16(0), u16(files.length), u16(files.length), u32(cdSize), u32(offset), u16(0))));
    parts.forEach(function (p) { total += p.length; });
    out = new Uint8Array(total);
    parts.forEach(function (p) { out.set(p, pos); pos += p.length; });
    return out;
  }
  function xesc(s) { return String(s).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function docxBytes(title, segLists, mode) {
    var FONT = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>';
    function run(text, it, bold, sz) {
      sz = sz || 24;
      return '<w:r><w:rPr>' + FONT + (bold ? '<w:b/>' : '') + (it && mode !== 'u' ? '<w:i/>' : '') + '<w:sz w:val="' + sz + '"/><w:szCs w:val="' + sz + '"/>' + (it && mode === 'u' ? '<w:u w:val="single"/>' : '') + '</w:rPr><w:t xml:space="preserve">' + xesc(text) + '</w:t></w:r>';
    }
    var body = '';
    if (title) body += '<w:p><w:pPr><w:spacing w:after="240"/></w:pPr>' + run(title, false, true, 28) + '</w:p>';
    segLists.forEach(function (seg, n) {
      body += '<w:p><w:pPr><w:spacing w:after="160"/><w:ind w:left="432" w:hanging="432"/></w:pPr>' + run((n + 1) + '. ', false) + seg.map(function (x) { return run(x.s, x.i); }).join('') + '</w:p>';
    });
    var head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
    var doc = head + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr></w:body></w:document>';
    var ct = head + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>';
    var rels = head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>';
    return zipStore([{ name: '[Content_Types].xml', data: utf8(ct) }, { name: '_rels/.rels', data: utf8(rels) }, { name: 'word/document.xml', data: utf8(doc) }]);
  }
  function mdText(title, segLists) {
    return (title ? '# ' + title + '\n\n' : '') + segLists.map(function (s, n) { return (n + 1) + '. ' + toMarkdown(s); }).join('\n') + '\n';
  }
  function csvCell(v) { v = String(v == null ? '' : v); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
  function csvText(states, typeLabels) {
    var rows = [['No.', 'Footnote', 'Short form', 'Source type', 'Authors', 'Editors', 'Translators', 'Contributors', 'Title', 'Title in English', 'Location', 'Kind of source', 'Details', 'Qualifiers', 'Original language', 'Access', 'Rating', 'Publisher', 'Date', 'Accessed', 'URL', 'Archive link', 'Archive captured', 'Locator', 'Commentary']];
    states.forEach(function (st, n) {
      var d = normDate(st.date), ppl = splitPeople(st);
      rows.push([n + 1, toPlain(build(st).seg), toPlain(shortForms(st).short), (typeLabels && typeLabels[st.type]) || st.type || '',
        lines(st.authors).join('; '), ppl.ed.join('; '), ppl.trans.join('; '), ppl.contr.join('; '), cleanTitle(st.title, 'plain'), cleanTitle(st.transTitle, 'plain'),
        clean(st.location), clean(st.descType), lines(st.descDetails).join('; '), (Array.isArray(st.quals) ? st.quals : []).join('; '), clean(st.origLang),
        accessOf(st).join('; '), /^[A-F][1-6]$/.test(st.rating || '') ? st.rating : '', clean(st.publisher),
        ((st.dateKind === 'updated' || st.dateKind === 'captured') && d.text ? st.dateKind + ' ' : '') + d.text, normDate(st.accessed).text,
        normUrl(st.url).url, normUrl(st.archiveUrl).url, normDate(st.archiveDate).text, normLocator(st.locator), clean(st.note)]);
    });
    return '﻿' + rows.map(function (r) { return r.map(csvCell).join(','); }).join('\r\n') + '\r\n';
  }
  function listFile(name, items) {
    return JSON.stringify({
      app: 'OSINT Citation Generator', format: 2, name: name || '', savedAt: new Date().toISOString(),
      sources: items.map(function (x) { return { id: x.id, footnote: toMarkdown(build(x.st).seg), fields: x.st }; })
    }, null, 2) + '\n';
  }
  function parseListFile(text, typeNames, textKeys) {
    var data;
    try { data = JSON.parse(String(text).replace(/^﻿/, '')); } catch (e) { return { error: 'That is not a list file from this tool. It could not be read.' }; }
    var arr = Array.isArray(data) ? data : (data && Array.isArray(data.sources) ? data.sources : null);
    if (!arr) return { error: 'That is not a list file from this tool. It holds no source list.' };
    function strArr(v) {
      var a = Array.isArray(v) ? v : (typeof v === 'string' && v ? [v] : []);
      return a.filter(function (x) { return typeof x === 'string'; }).map(function (x) { return x.slice(0, 200); }).slice(0, 40);
    }
    var items = [], seen = {};
    arr.slice(0, 5000).forEach(function (x, n) {
      var f = x && typeof x === 'object' ? (x.fields || x.st) : null;
      if (!f || typeof f !== 'object') return;
      var st = {};
      textKeys.forEach(function (k) { st[k] = typeof f[k] === 'string' ? f[k].slice(0, 8000) : ''; });
      st.type = typeNames.indexOf(f.type) !== -1 ? f.type : 'web';
      st.access = strArr(f.access); st.quals = strArr(f.quals);
      st.shortUseTitle = f.shortUseTitle !== false;
      var up = upgradeState({ editors: st.editors, translators: st.translators, contributors: st.contributors,
        contribs: typeof f.contribs === 'string' ? f.contribs.slice(0, 8000) : '', contribRole: typeof f.contribRole === 'string' ? f.contribRole : '',
        transTitle: st.transTitle, origLang: st.origLang, transBy: st.transBy, langMode: f.langMode });
      st.editors = up.editors; st.translators = up.translators; st.contributors = up.contributors; st.langMode = up.langMode;
      if (build(st).empty) return;
      var id = typeof x.id === 'string' && x.id && x.id.length <= 80 ? x.id : 'f' + n + '-' + Math.floor(Math.random() * 1e9);
      if (seen[id]) id += '-' + n;
      seen[id] = 1;
      items.push({ id: id, st: st });
    });
    return { name: data && typeof data.name === 'string' ? data.name.slice(0, 200) : '', items: items };
  }

  // ---- reading a link: what the address alone can tell us ----
  // Each entry: host -> [source type, location, kind of source, extra fields].
  var SITES = {
    'nytimes.com': ['news', 'The New York Times', 'News Article'], 'washingtonpost.com': ['news', 'The Washington Post', 'News Article'],
    'wsj.com': ['news', 'The Wall Street Journal', 'News Article'], 'ft.com': ['news', 'Financial Times', 'News Article'],
    'reuters.com': ['news', 'Reuters', 'Wire Service Report'], 'apnews.com': ['news', 'AP News', 'Wire Service Report'],
    'bbc.com': ['news', 'BBC News', 'News Article'], 'bbc.co.uk': ['news', 'BBC News', 'News Article'],
    'theguardian.com': ['news', 'The Guardian', 'News Article'], 'economist.com': ['news', 'The Economist', 'Magazine Article'],
    'bloomberg.com': ['news', 'Bloomberg', 'News Article'], 'politico.com': ['news', 'Politico', 'News Article'], 'politico.eu': ['news', 'Politico', 'News Article'],
    'aljazeera.com': ['news', 'Al Jazeera', 'News Article'], 'cnn.com': ['news', 'CNN', 'News Article'], 'npr.org': ['news', 'NPR', 'News Article'],
    'axios.com': ['news', 'Axios', 'News Article'], 'thehill.com': ['news', 'The Hill', 'News Article'], 'propublica.org': ['news', 'ProPublica', 'Investigative Report'],
    'foreignpolicy.com': ['news', 'Foreign Policy', 'Magazine Article'], 'foreignaffairs.com': ['news', 'Foreign Affairs', 'Magazine Article'],
    'theatlantic.com': ['news', 'The Atlantic', 'Magazine Article'], 'thediplomat.com': ['news', 'The Diplomat', 'Magazine Article'],
    'defensenews.com': ['news', 'Defense News', 'News Article'], 'breakingdefense.com': ['news', 'Breaking Defense', 'News Article'],
    'twz.com': ['news', 'The War Zone', 'News Article'], 'navalnews.com': ['news', 'Naval News', 'News Article'], 'news.usni.org': ['news', 'USNI News', 'News Article'],
    'janes.com': ['news', 'Janes', 'News Article'], 'militarytimes.com': ['news', 'Military Times', 'News Article'], 'stripes.com': ['news', 'Stars and Stripes', 'News Article'],
    'c4isrnet.com': ['news', 'C4ISRNET', 'News Article'], 'kyivindependent.com': ['news', 'The Kyiv Independent', 'News Article'], 'kyivpost.com': ['news', 'Kyiv Post', 'News Article'],
    'meduza.io': ['news', 'Meduza', 'News Article'], 'themoscowtimes.com': ['news', 'The Moscow Times', 'News Article'], 'scmp.com': ['news', 'South China Morning Post', 'News Article'],
    'japantimes.co.jp': ['news', 'The Japan Times', 'News Article'], 'asia.nikkei.com': ['news', 'Nikkei Asia', 'News Article'], 'timesofisrael.com': ['news', 'The Times of Israel', 'News Article'],
    'haaretz.com': ['news', 'Haaretz', 'News Article'], 'dw.com': ['news', 'DW', 'News Article'], 'france24.com': ['news', 'France 24', 'News Article'],
    'rferl.org': ['news', 'Radio Free Europe/Radio Liberty', 'News Article'],
    'tass.com': ['news', 'TASS', 'State Media Report'], 'rt.com': ['news', 'RT', 'State Media Report'], 'sputnikglobe.com': ['news', 'Sputnik', 'State Media Report'],
    'xinhuanet.com': ['news', 'Xinhua', 'State Media Report'], 'news.cn': ['news', 'Xinhua', 'State Media Report'], 'globaltimes.cn': ['news', 'Global Times', 'State Media Report'],
    'chinadaily.com.cn': ['news', 'China Daily', 'State Media Report'], 'cgtn.com': ['news', 'CGTN', 'State Media Report'], 'presstv.ir': ['news', 'Press TV', 'State Media Report'],
    'kcna.kp': ['news', 'KCNA', 'State Media Report'], 'irna.ir': ['news', 'IRNA', 'State Media Report'],
    'warontherocks.com': ['web', 'War on the Rocks', 'Defense Analysis Article'], 'mwi.westpoint.edu': ['web', 'Modern War Institute', 'Defense Analysis Article'],
    'csis.org': ['web', 'CSIS', 'Policy Analysis'], 'brookings.edu': ['web', 'Brookings', 'Policy Analysis'], 'carnegieendowment.org': ['web', 'Carnegie Endowment for International Peace', 'Policy Analysis'],
    'atlanticcouncil.org': ['web', 'Atlantic Council', 'Policy Analysis'], 'cnas.org': ['web', 'CNAS', 'Policy Analysis'], 'iiss.org': ['web', 'IISS', 'Policy Analysis'],
    'rusi.org': ['web', 'RUSI', 'Policy Analysis'], 'cfr.org': ['web', 'Council on Foreign Relations', 'Policy Analysis'], 'chathamhouse.org': ['web', 'Chatham House', 'Policy Analysis'],
    'ecfr.eu': ['web', 'ECFR', 'Policy Analysis'], 'fpri.org': ['web', 'FPRI', 'Policy Analysis'], 'lowyinstitute.org': ['web', 'Lowy Institute', 'Policy Analysis'],
    'stimson.org': ['web', 'Stimson Center', 'Policy Analysis'], '38north.org': ['web', '38 North', 'Policy Analysis'], 'jamestown.org': ['web', 'The Jamestown Foundation', 'Policy Analysis'],
    'sipri.org': ['web', 'SIPRI', 'Policy Analysis'], 'rand.org': ['web', 'RAND', 'Think Tank Report'],
    'understandingwar.org': ['web', 'Institute for the Study of War', 'Campaign Assessment'], 'criticalthreats.org': ['web', 'Critical Threats', 'Campaign Assessment'],
    'bellingcat.com': ['web', 'Bellingcat', 'Open-Source Investigation'], 'lawfaremedia.org': ['web', 'Lawfare', 'Expert Commentary'], 'justsecurity.org': ['web', 'Just Security', 'Expert Commentary'],
    'substack.com': ['web', 'Substack', 'Newsletter Article'], 'medium.com': ['web', 'Medium', 'Blog Post'], 'wikipedia.org': ['web', 'Wikipedia', 'Wiki Article'],
    'ssrn.com': ['journal', 'SSRN', 'Preprint Paper'],
    'whitehouse.gov': ['web', 'White House Government Website', 'Government Web Page', { publisher: 'US Government' }],
    'defense.gov': ['web', 'Defense Department Website', 'Government Web Page', { publisher: 'US Government' }], 'war.gov': ['web', 'Defense Department Website', 'Government Web Page', { publisher: 'US Government' }],
    'state.gov': ['web', 'State Department Website', 'Government Web Page', { publisher: 'US Government' }], 'justice.gov': ['web', 'US Dept. of Justice Website', 'Government Web Page', { publisher: 'US Government' }],
    'treasury.gov': ['web', 'US Treasury Dept. Website', 'Government Web Page', { publisher: 'US Government' }],
    'sanctionslist.ofac.treas.gov': ['live', 'US Treasury Dept. Website', 'Sanctions List', { publisher: 'US Government', authors: 'US Department of the Treasury' }],
    'crsreports.congress.gov': ['report', 'CRS Reports Website', 'CRS Report', { publisher: 'US Congress', authors: 'Congressional Research Service' }],
    'congress.gov': ['web', 'Congress.gov', 'Government Web Page', { publisher: 'US Congress' }], 'gao.gov': ['report', 'GAO Website', 'GAO Report', { publisher: 'GAO', authors: 'US Government Accountability Office' }],
    'federalregister.gov': ['web', 'Federal Register', 'Federal Register Notice', { publisher: 'US Government' }], 'archives.gov': ['archival', 'US National Archives Website', 'Archival Material'],
    'gov.uk': ['web', 'UK Government Website', 'Government Web Page', { publisher: 'UK Government' }], 'nato.int': ['web', 'NATO Website', 'NATO Publication', { publisher: 'NATO' }],
    'un.org': ['web', 'UN Website', '', { publisher: 'UN' }], 'undocs.org': ['report', 'UN Website', '', { publisher: 'UN' }], 'iaea.org': ['web', 'IAEA Website', '', { publisher: 'IAEA' }],
    'flightradar24.com': ['live', 'Flightradar24', 'Flight Tracking Data'], 'adsbexchange.com': ['live', 'ADS-B Exchange', 'Flight Tracking Data'],
    'marinetraffic.com': ['live', 'MarineTraffic', 'Ship Tracking (AIS)'], 'vesselfinder.com': ['live', 'VesselFinder', 'Ship Tracking (AIS)'],
    'liveuamap.com': ['live', 'Liveuamap', 'Interactive Map'], 'deepstatemap.live': ['live', 'DeepStateMAP', 'Control-of-Terrain Map'],
    'facebook.com': ['social', 'Facebook', 'Social Media Post'], 'instagram.com': ['social', 'Instagram', 'Social Media Post'], 'threads.net': ['social', 'Threads', 'Social Media Post'],
    'threads.com': ['social', 'Threads', 'Social Media Post'], 'linkedin.com': ['social', 'LinkedIn', 'Social Media Post'], 'reddit.com': ['social', 'Reddit', 'Forum Post'],
    'vk.com': ['social', 'VK', 'Social Media Post'], 'weibo.com': ['social', 'Weibo', 'Social Media Post'], 'truthsocial.com': ['social', 'Truth Social', 'Social Media Post'],
    'vimeo.com': ['video', 'Vimeo', 'Video'], 'rumble.com': ['video', 'Rumble', 'Video'], 'odysee.com': ['video', 'Odysee', 'Video']
  };
  var ARCHIVE_HOSTS = ['archive.ph', 'archive.today', 'archive.is', 'archive.md', 'archive.li', 'archive.vn', 'archive.fo'];
  var TRACKERS = /^(utm_[a-z_]+|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid|igshid|igsh|ref_src|ref_url|smid|smtyp|cmpid|ocid|ncid|taid|at_medium|at_campaign|__twitter_impression)$/i;
  var B32 = '234567abcdefghijklmnopqrstuvwxyz';

  function siteFor(host) {
    var h = host, i;
    while (h) { if (SITES[h]) return SITES[h]; i = h.indexOf('.'); if (i < 0) break; h = h.slice(i + 1); }
    return null;
  }
  function utcDate(ms) { var d = new Date(ms); return pad2(d.getUTCDate()) + ' ' + MONTHS[d.getUTCMonth()] + ' ' + d.getUTCFullYear(); }
  function shiftRight(idText, bits) {
    if (typeof BigInt !== 'function') return NaN;
    try { return Number(BigInt(idText) >> BigInt(bits)); } catch (e) { return NaN; }
  }
  function clockOf(t) {
    var m = String(t).match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$/), secs, h, mi, s;
    if (!m || !(m[1] || m[2] || m[3])) return '';
    secs = (+m[1] || 0) * 3600 + (+m[2] || 0) * 60 + (+m[3] || 0);
    if (!secs) return '';
    h = Math.floor(secs / 3600); mi = Math.floor((secs % 3600) / 60); s = secs % 60;
    return (h ? h + ':' + pad2(mi) : String(mi)) + ':' + pad2(s);
  }
  function parseUrl(s) {
    var u;
    try { u = new URL(s); } catch (e) { return null; }
    if (!/^https?:$/.test(u.protocol) || u.hostname.indexOf('.') < 0) return null;
    return u;
  }

  function readLink(raw, nowMs, todayText) {
    var now = nowMs || Date.now(), s = String(raw == null ? '' : raw).trim(), u, m, f = {}, notes = [], type = '', known = false;
    if (!s || /\s/.test(s)) return null;
    u = parseUrl(normUrl(s).url);
    if (!u) return null;
    var today = todayText || utcDate(now);
    var host = u.hostname.toLowerCase().replace(/^(www|m|mobile)\./, '');

    // An archive link: keep it as the archive, and read the original address and capture date out of it.
    var orig = '';
    if (host === 'web.archive.org' && (m = u.pathname.match(/^\/web\/(\d{4})(\d{2})(\d{2})\d{0,6}[a-z_]*\/(.+)$/))) orig = m[4];
    else if (ARCHIVE_HOSTS.indexOf(host) !== -1) {
      if ((m = u.pathname.match(/^\/(\d{4})\.(\d{2})\.(\d{2})-\d{6}\/(.+)$/))) orig = m[4];
      else { f.archiveUrl = u.href; notes.push('This is an archive link with no original address in it. Paste the original link too.'); return { type: '', fields: f, notes: notes, known: false }; }
    }
    if (orig) {
      var inner = parseUrl(normUrl(orig + u.search + u.hash).url);
      f.archiveUrl = u.href;
      if (+m[2] >= 1 && +m[2] <= 12 && +m[3] >= 1 && +m[3] <= 31) f.archiveDate = pad2(+m[3]) + ' ' + MONTHS[+m[2] - 1] + ' ' + m[1];
      notes.push('This is an archive link, so it went in as the archive copy and the original address was read from it.');
      if (!inner) return { type: '', fields: f, notes: notes, known: false };
      u = inner; host = u.hostname.toLowerCase().replace(/^(www|m|mobile)\./, '');
    }

    function dateFromId(ms, minYear, why) {
      if (isFinite(ms) && ms >= Date.UTC(minYear, 0, 1) && ms <= now + 1728e5) { f.date = utcDate(ms); notes.push(why); }
    }
    function dropParams(test) {
      var keep = [], dropped = false;
      u.searchParams.forEach(function (v, k) { if (test(k)) dropped = true; else keep.push([k, v]); });
      if (!dropped) return;
      u.search = '';
      keep.forEach(function (kv) { u.searchParams.append(kv[0], kv[1]); });
    }
    var seg = u.pathname.split('/').filter(Boolean), handleNote = 'The author is the handle from the link. Use the account name instead if it differs.';
    dropParams(function (k) { return TRACKERS.test(k); });
    if (/^#:~:/.test(u.hash)) u.hash = '';

    if (host === 'x.com' || host === 'twitter.com') {
      type = 'social'; known = true; f.location = 'X'; f.descType = 'Social Media Post';
      if (seg.length >= 3 && seg[1] === 'status' && /^\d+$/.test(seg[2])) {
        if (!/^(i|intent|home|search)$/.test(seg[0])) { f.authors = '@' + seg[0]; notes.push(handleNote); }
        if (seg[2].length >= 15) dateFromId(shiftRight(seg[2], 22) + 1288834974657, 2010, 'The date was read from the post ID and is in UTC.');
        u.search = ''; u.pathname = '/' + seg.slice(0, 3).join('/');
      } else if (seg.length === 1) { f.authors = '@' + seg[0]; f.descType = 'Account Profile'; }
    } else if (host === 't.me' || host === 'telegram.me') {
      type = 'social'; known = true; f.location = 'Telegram'; f.descType = 'Channel Post';
      if (seg[0] === 's') { seg = seg.slice(1); u.pathname = '/' + seg.join('/'); }
      if (seg[0] === 'c') notes.push('This is a private-channel link. Readers without access cannot open it, so say that in the commentary.');
      else if (seg[0] && !/^(joinchat|addstickers|share|\+)/.test(seg[0])) { f.authors = seg[0]; notes.push('The author is the channel name from the link. Use the channel\'s display name if it differs.'); }
    } else if (host === 'youtube.com' || host === 'youtu.be' || host === 'music.youtube.com') {
      type = 'video'; known = true; f.location = 'YouTube'; f.descType = seg[0] === 'shorts' ? 'Short-Form Video' : 'Video';
      var t = clockOf(u.searchParams.get('t') || u.searchParams.get('start') || '');
      if (t) { f.locator = 'See ' + t; notes.push('The link pointed at a moment in the video, which went in as the locator.'); }
      dropParams(function (k) { return /^(si|feature|pp|t|start)$/.test(k); });
    } else if (host === 'tiktok.com') {
      type = 'social'; known = true; f.location = 'TikTok'; f.descType = 'Short-Form Video';
      if (seg[0] && seg[0].charAt(0) === '@') { f.authors = seg[0]; notes.push(handleNote); }
      if (seg[1] === 'video' && /^\d{17,}$/.test(seg[2] || '')) dateFromId(shiftRight(seg[2], 32) * 1000, 2016, 'The date was read from the video ID and is in UTC.');
      u.search = '';
    } else if (host === 'bsky.app') {
      type = 'social'; known = true; f.location = 'Bluesky'; f.descType = 'Social Media Post';
      if (seg[0] === 'profile' && seg[1]) { f.authors = '@' + seg[1]; notes.push(handleNote); }
      if (seg[2] === 'post' && /^[234567a-z]{13}$/.test(seg[3] || '')) {
        var v = 0, i;
        for (i = 0; i < 13; i++) v = v * 32 + B32.indexOf(seg[3].charAt(i));
        dateFromId(v / 1024 / 1000, 2022, 'The date was read from the post ID and is in UTC.');
      }
    } else if (host === 'discord.com' || host === 'discordapp.com') {
      type = 'social'; known = true; f.location = 'Discord'; f.descType = 'Group Chat Message';
      if (seg[0] === 'channels' && /^\d{15,}$/.test(seg[3] || '')) dateFromId(shiftRight(seg[3], 22) + 1420070400000, 2015, 'The date was read from the message ID and is in UTC.');
      notes.push('Discord links open only for members of that server, so say that in the commentary.');
    } else if (host === 'github.com' && seg.length >= 2) {
      type = 'web'; known = true; f.location = 'GitHub'; f.descType = 'Code Repository'; f.authors = seg[0]; f.title = seg[1];
    } else if (host === 'arxiv.org' && (m = u.pathname.match(/^\/(?:abs|pdf)\/(\d{2})(\d{2})\.\d{4,5}/))) {
      type = 'journal'; known = true; f.location = 'arXiv'; f.descType = 'Preprint Paper';
      if (+m[2] >= 1 && +m[2] <= 12) { f.date = MONTHS[+m[2] - 1] + ' 20' + m[1]; notes.push('The month was read from the arXiv number.'); }
    } else if (host === 'doi.org') {
      type = 'journal'; known = true;
    } else if ((host === 'google.com' && seg[0] === 'maps') || host === 'maps.google.com' || host === 'earth.google.com') {
      type = 'imagery'; known = true; f.location = host === 'earth.google.com' ? 'Google Earth' : 'Google Maps'; f.accessed = today;
      if ((m = u.pathname.match(/@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)/))) {
        f.descDetails = Math.abs(+m[1]).toFixed(4) + '° ' + (+m[1] < 0 ? 'S' : 'N') + ', ' + Math.abs(+m[2]).toFixed(4) + '° ' + (+m[2] < 0 ? 'W' : 'E');
        notes.push('The coordinates were read from the link.');
      }
    } else {
      var site = siteFor(host);
      if (site) {
        type = site[0]; known = true; f.location = site[1];
        if (site[2]) f.descType = site[2];
        if (site[3]) Object.keys(site[3]).forEach(function (k) { f[k] = site[3][k]; });
        if (host.slice(-13) === '.substack.com') f.publisher = host.slice(0, -13);
        if (host === 'instagram.com' && (seg[0] === 'reel' || seg[0] === 'reels')) f.descType = 'Short-Form Video';
        if (host === 'reddit.com' && seg[0] === 'r' && seg[1]) f.descDetails = 'r/' + seg[1];
        if ((host === 'threads.net' || host === 'threads.com' || host === 'truthsocial.com') && seg[0] && seg[0].charAt(0) === '@') { f.authors = seg[0]; notes.push(handleNote); }
        if (type === 'live') f.accessed = today;
      } else if (/\.(gov|mil)$/.test(host)) {
        type = 'web'; f.descType = 'Government Web Page';
      }
    }
    var pdf = /\.pdf$/i.test(u.pathname);
    if (pdf && (type === 'web' || type === 'news' || type === '')) { type = 'report'; if (f.descType === 'Government Web Page') delete f.descType; }

    // A date in the path, unless the path is an upload folder (those carry the upload month, not the publication date).
    if (!f.date && !/\/(wp-content|uploads|files|sites\/default|media|assets|images|static)\//i.test(u.pathname)) {
      var p = u.pathname;
      if ((m = p.match(/\/((?:19|20)\d{2})[\/-](\d{1,2})[\/-](\d{1,2})(?:[\/-]|$)/)) || (m = p.match(/\/((?:19|20)\d{2})(\d{2})(\d{2})(?:[\/-]|$)/)) || (m = p.match(/-((?:19|20)\d{2})-(\d{2})-(\d{2})(?:\/|$)/))) {
        if (+m[2] >= 1 && +m[2] <= 12 && +m[3] >= 1 && +m[3] <= 31) { f.date = pad2(+m[3]) + ' ' + MONTHS[+m[2] - 1] + ' ' + m[1]; notes.push('The date was read from the link. Check it against the page.'); }
      } else if ((m = p.match(/\/((?:19|20)\d{2})\/(\d{1,2})\//)) && +m[2] >= 1 && +m[2] <= 12) {
        f.date = MONTHS[+m[2] - 1] + ' ' + m[1]; notes.push('Only the month is in the link. Add the day from the page.');
      }
    }
    if (!known && !f.descType) notes.push('This site is not one the tool knows, so only the link' + (f.date ? ' and date were' : ' was') + ' read.');
    f.url = u.href;
    return { type: type, fields: f, notes: notes, known: known };
  }

  // ---- auditing a whole list ----
  function auditList(states) {
    var rows = [], flagged = {}, byUrl = {}, byShort = {}, unrated = 0, total = 0;
    states.forEach(function (st, i) {
      var n = i + 1, r = build(st), u, sf;
      if (r.empty) return;
      total++;
      r.checks.forEach(function (c) { if (c.level !== 'note') { rows.push({ n: n, level: c.level, msg: c.msg }); flagged[n] = 1; } });
      if (!r.rating && !st.ai) unrated++;
      u = normUrl(st.url).url.replace(/#.*$/, '').replace(/\/$/, '');
      if (u) (byUrl[u] = byUrl[u] || []).push(n);
      sf = toPlain(shortForms(Object.assign({}, st, { locator: '' })).short);
      if (sf) (byShort[sf] = byShort[sf] || []).push({ n: n, u: u });
    });
    Object.keys(byUrl).forEach(function (u) {
      var g = byUrl[u];
      if (g.length < 2) return;
      rows.push({ n: g[0], nums: g, level: 'check', msg: 'Sources ' + listJoin(g.map(String)) + ' cite the same link. If this is one source cited more than once, keep one entry and use its short form for the later citations.' });
      g.forEach(function (x) { flagged[x] = 1; });
    });
    Object.keys(byShort).forEach(function (k) {
      var g = byShort[k], sameLink = g.every(function (x) { return x.u && x.u === g[0].u; }), nums;
      if (g.length < 2 || sameLink) return;
      nums = g.map(function (x) { return x.n; });
      rows.push({ n: nums[0], nums: nums, level: 'check', msg: 'Sources ' + listJoin(nums.map(String)) + ' share the short form ' + k + ' Give each a short title that tells them apart.' });
      nums.forEach(function (x) { flagged[x] = 1; });
    });
    var order = { fix: 0, check: 1 };
    rows.sort(function (a, b) { return a.n - b.n || order[a.level] - order[b.level]; });
    return { total: total, attention: Object.keys(flagged).length, unrated: unrated, rows: rows };
  }

  var LIB_INDEX = {};
  function setLibrary(idx) { LIB_INDEX = idx || {}; }

  return { build: build, shortForms: shortForms, setLibrary: setLibrary, accessOf: accessOf, toHTML: toHTML, toMarkdown: toMarkdown, toPlain: toPlain, joinSources: joinSources, docxBytes: docxBytes, mdText: mdText, csvText: csvText, listFile: listFile, parseListFile: parseListFile, readLink: readLink, auditList: auditList, splitPeople: splitPeople, langModeOf: langModeOf, upgradeState: upgradeState,
    normDate: normDate, normLocator: normLocator, normUrl: normUrl, zoneOf: zoneOf, REL: REL, CRED: CRED, ZNAME: ZNAME, MONTHS: MONTHS, esc: esc };
})();
