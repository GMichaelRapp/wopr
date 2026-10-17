#!/usr/bin/env python3
"""WOPR newsfeed builder.

Reads feeds.yaml, fetches every source, merges new stories into a rolling
archive (data/items.json), and writes the site to docs/:

  docs/index.html     the newsfeed page (headline on top, link directly below,
                      OSINT citation per story, a source list you can print)
  docs/osint-core.js  the OSINT Citation Generator's formatter
  docs/status.html    which sources worked on the last run and which failed
  docs/feed.xml       everything on the page as one combined RSS feed
  docs/feed.json      the same as JSON

Run locally:  pip install -r requirements.txt && python build.py
"""

import calendar
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.utils import formatdate
from pathlib import Path
from urllib.parse import parse_qsl, quote_plus, urlencode, urljoin, urlsplit, urlunsplit
from xml.sax.saxutils import escape as xml_escape, quoteattr
from zoneinfo import ZoneInfo

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "feeds.yaml"
ARCHIVE = ROOT / "data" / "items.json"
CORE_FALLBACK = ROOT / "vendor" / "osint-core.js"
SOURCES_DIR = ROOT / "sources"
OUT = ROOT / "docs"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 PersonalNewsfeed/1.0"
)

DEFAULTS = {
    "title": "WOPR",
    "timezone": "America/Denver",
    "page_hours": 72,
    "max_page_items": 1500,
    "archive_days": 30,
    "gnews_days": 3,
    "timeout": 20,
    "workers": 16,
    "gnews_workers": 4,
    "exclude": [],
    "osint_generator": "https://gmichaelrapp.github.io/OSINT_Cites/",
}

# Colors for beat accents; mid-tones that read on light and dark backgrounds.
PALETTE = [
    "#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899",
    "#14b8a6", "#f97316", "#6366f1", "#84cc16", "#06b6d4", "#e11d48",
    "#a855f7", "#22c55e", "#eab308",
]

TRACKING_PARAMS = re.compile(
    r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|cmpid|s_cid|smid|"
    r"ito|taid|guccounter|_hsenc|_hsmi|mkt_tok|ocid|cid)$",
    re.I,
)

# Which OSINT Cites source type a kind of source belongs to. The type sets
# the title style (quotes or italics) and the generator's checks.
DESC_TYPES = {
    "news": {"News Article", "Wire Service Report", "News Analysis", "Magazine Article",
             "Investigative Report", "Feature Article", "Editorial / Op-Ed", "Explainer",
             "State Media Report", "Fact-Check"},
    "report": {"GAO Report", "CRS Report", "Government Report", "Think Tank Report",
               "Research Report", "Defense White Paper", "National Strategy Document"},
    "social": {"Forum Post", "Social Media Post", "Thread", "Channel Post", "Video Post",
               "Short-Form Video"},
    "video": {"Video", "Podcast", "Recorded Interview"},
}


DESC_SUGGESTIONS = [
    "News Article", "Wire Service Report", "News Analysis", "Investigative Report", "Magazine Article",
    "Editorial / Op-Ed", "State Media Report", "Expert Commentary", "Policy Analysis", "Policy Brief",
    "Think Tank Report", "Defense Analysis Article", "Open-Source Investigation", "Research Report",
    "Newsletter Article", "Journalist Newsletter", "Blog Post", "Security Blog Post", "Corporate Blog Post",
    "Threat Intelligence Report", "Security Advisory", "Government Press Release", "Government Web Page",
    "Government Report", "GAO Report", "CRS Report", "Forum Post", "Social Media Post", "Video", "Podcast",
]


def source_type(desc):
    for kind, names in DESC_TYPES.items():
        if desc in names:
            return kind
    return "web"


# ---------------------------------------------------------------- config

def gnews_url(query):
    return (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "misc"


def as_list(value):
    if not value:
        return []
    return [str(v) for v in (value if isinstance(value, list) else [value])]


def read_added_sources(beat_map):
    """Merge sources/*.yaml (sources added from the page) into the beat map."""
    for path in sorted(SOURCES_DIR.glob("*.y*ml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            print(f"  ! skipped {path.name}: not valid YAML ({exc})")
            continue
        if not isinstance(data, dict):
            print(f"  ! skipped {path.name}: expected 'beat' and 'sources'")
            continue
        groups = dict(data.get("beats") or {})
        if data.get("beat") and data.get("sources"):
            groups.setdefault(str(data["beat"]), [])
            groups[str(data["beat"])] = list(groups[str(data["beat"])]) + list(data["sources"])
        for beat, entries in groups.items():
            for entry in entries or []:
                if isinstance(entry, dict):
                    entry = {**entry, "added_in": path.name}
                beat_map.setdefault(str(beat), []).append(entry)


def load_config():
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    settings = {**DEFAULTS, **(raw.get("settings") or {})}
    # Where the "Add a source" form sends you: the repo this build runs in.
    settings.setdefault("repo", os.environ.get("GITHUB_REPOSITORY", ""))
    settings.setdefault("branch", os.environ.get("GITHUB_REF_NAME", "") or "main")
    days = int(settings["gnews_days"])
    beat_map = {str(b): list(v or []) for b, v in (raw.get("beats") or {}).items()}
    read_added_sources(beat_map)
    feeds, beats = [], []
    for beat, entries in beat_map.items():
        beats.append(beat)
        for entry in entries or []:
            if isinstance(entry, str):
                entry = {"query": entry}
            if not isinstance(entry, dict) or entry.get("enabled") is False:
                continue
            if entry.get("url"):
                url, kind = entry["url"], "direct"
                name = entry.get("name") or urlsplit(url).netloc
            elif entry.get("site"):
                url = gnews_url(f"site:{entry['site']} when:{days}d")
                kind = "gnews-site"
                name = entry.get("name") or entry["site"]
            elif entry.get("query"):
                url = gnews_url(f"{entry['query']} when:{days}d")
                kind = "gnews-query"
                name = entry.get("name") or f"Search: {entry['query']}"
            else:
                print(f"  ! skipped an entry in '{beat}' with no url/site/query: {entry}")
                continue
            feeds.append({
                "name": str(name),
                "beat": beat,
                "url": url,
                "kind": kind,
                "include": [str(k).lower() for k in entry.get("include") or []],
                # citation defaults for every story from this source
                "location": entry.get("location"),
                "desc": entry.get("desc"),
                "details": entry.get("details"),
                "publisher": entry.get("publisher"),
                "author": entry.get("author"),
                "access": as_list(entry.get("access")),
                "added_in": entry.get("added_in"),
                "spec": {k: entry[k] for k in ("url", "site", "query") if entry.get(k)},
            })
    return settings, feeds, beats


# ---------------------------------------------------------------- fetching

def fetch_bytes(url, timeout):
    resp = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.content


ALT_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)


def discover_feed(page_bytes, base_url):
    """Find the RSS/Atom feed a web page points to, if any."""
    text = page_bytes[:400_000].decode("utf-8", "replace")
    for tag in ALT_LINK_RE.findall(text):
        low = tag.lower()
        if "alternate" in low and ("rss+xml" in low or "atom+xml" in low or "feed+json" in low):
            href = re.search(r'href\s*=\s*["\']([^"\']+)', tag, re.I)
            if href:
                return urljoin(base_url, html.unescape(href.group(1)))
    return None


def fetch_feed(feed, timeout):
    start = time.time()
    try:
        content = fetch_bytes(feed["url"], timeout)
        parsed = feedparser.parse(content)
        if not parsed.entries and feed["kind"] == "direct" and b"<html" in content[:5000].lower():
            # A web page rather than a feed: follow the feed it advertises.
            found = discover_feed(content, feed["url"])
            if not found:
                raise ValueError("a web page with no feed link; find its RSS address or use site: instead")
            feed["discovered"] = found
            parsed = feedparser.parse(fetch_bytes(found, timeout))
        if not parsed.entries and parsed.bozo:
            exc = parsed.get("bozo_exception")
            raise ValueError(f"not a readable feed ({type(exc).__name__})")
        feed["feed_title"] = clean_text(parsed.feed.get("title"))
        return feed, parsed.entries, None, time.time() - start
    except Exception as exc:  # one bad source must never stop the build
        msg = str(exc).replace("\n", " ")
        return feed, [], msg[:220], time.time() - start


def fetch_all(feeds, settings):
    direct = [f for f in feeds if f["kind"] == "direct"]
    google = [f for f in feeds if f["kind"] != "direct"]
    timeout = settings["timeout"]
    # Google News gets fewer parallel requests so it doesn't throttle us.
    with ThreadPoolExecutor(settings["workers"]) as pool_a, \
         ThreadPoolExecutor(settings["gnews_workers"]) as pool_b:
        futures = [pool_a.submit(fetch_feed, f, timeout) for f in direct]
        futures += [pool_b.submit(fetch_feed, f, timeout) for f in google]
        return [fut.result() for fut in futures]


def get_osint_core(settings):
    """The OSINT Cites formatter: the live copy if reachable, else the vendored one."""
    url = settings.get("osint_generator")
    if url:
        try:
            page = fetch_bytes(url, settings["timeout"]).decode("utf-8", "replace")
            match = re.search(r'<script id="core">([\s\S]*?)</script>', page)
            if match and "var OSINT" in match.group(1):
                return match.group(1).strip() + "\n", "current copy from OSINT Cites"
        except Exception as exc:
            print(f"  ! could not fetch the OSINT Cites formatter ({exc}); using the saved copy")
    return CORE_FALLBACK.read_text(encoding="utf-8"), "saved copy in vendor/"


# ---------------------------------------------------------------- items

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def clean_text(text):
    text = TAG_RE.sub(" ", text or "")
    return SPACE_RE.sub(" ", html.unescape(text)).strip()


def normalize_url(url):
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not TRACKING_PARAMS.match(k)]
    host = parts.netloc.lower()
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower() or "https", host, path, urlencode(query), ""))


def url_key(url):
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}?{parts.query}"


def title_key(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def entry_time(entry, now):
    """(timestamp, undated) for a feed entry."""
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(field)
        if value:
            try:
                ts = calendar.timegm(value)
            except (TypeError, ValueError, OverflowError):
                continue
            return min(ts, now), False  # clamp future-dated stories
    return now, True  # undated: sorted as first seen, but not cited with a date


def domain_of(url):
    return urlsplit(url or "").netloc.lower().removeprefix("www.")


EMAIL_WITH_NAME = re.compile(r"^\S+@\S+\s*\((.+)\)$")
JUST_EMAIL = re.compile(r"^\S+@\S+$")


def clean_author(name):
    name = clean_text(name)
    match = EMAIL_WITH_NAME.match(name)
    if match:
        name = match.group(1).strip()
    name = re.sub(r"^by\s+", "", name, flags=re.I).strip()
    if not name or JUST_EMAIL.match(name):
        return ""
    return name


def entry_authors(entry):
    names = []
    for author in entry.get("authors") or []:
        raw = author.get("name") if isinstance(author, dict) else str(author)
        name = clean_author(raw or "")
        if name and name not in names:
            names.append(name)
    if not names and entry.get("author"):
        name = clean_author(entry.get("author"))
        if name:
            names = [name]
    # "Jane Doe and John Roe" or "A, B and C" in one string: split when every
    # piece looks like a full name, so the formatter can join them house style.
    if len(names) == 1:
        parts = [p.strip() for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", names[0]) if p.strip()]
        if len(parts) > 1 and all(len(p.split()) >= 2 for p in parts):
            names = parts
    return names


def to_item(entry, feed, now, exclude):
    title = clean_text(entry.get("title"))
    link = (entry.get("link") or "").strip()
    if not title or not link.startswith("http"):
        return None

    source = feed["name"]
    home = None
    gnews = feed["kind"].startswith("gnews")
    location = feed.get("location")
    if location == "feed":
        location = feed.get("feed_title") or feed["name"]
    if gnews:
        src = entry.get("source") or {}
        publisher = clean_text(src.get("title"))
        if publisher:
            suffix = " - " + publisher
            if title.endswith(suffix):
                title = title[: -len(suffix)].rstrip()
            if feed["kind"] == "gnews-query":
                source = publisher
        home = domain_of(src.get("href")) or None

    haystack = title.lower()
    if feed["include"]:
        haystack_full = haystack + " " + clean_text(entry.get("summary")).lower()
        if not any(k in haystack_full for k in feed["include"]):
            return None
    if any(w.lower() in haystack for w in exclude):
        return None

    ts, undated = entry_time(entry, now)
    desc = feed.get("desc") or "News Article"
    link = normalize_url(link)
    item = {
        "id": url_key(link),
        "title": title,
        "link": link,
        "source": source,
        "beat": feed["beat"],
        "ts": ts,
        "home": home,
        "via": "Google News" if gnews else None,
        "also": [],
        # citation fields
        "authors": entry_authors(entry) or ([str(feed["author"])] if feed.get("author") else []),
        "location": location or source,
        "desc": desc,
        "desc_default": not feed.get("desc"),
        "ctype": source_type(desc),
    }
    for key in ("details", "publisher"):
        if feed.get(key):
            item[key] = str(feed[key])
    if feed.get("access"):
        item["access"] = feed["access"]
    if gnews:
        item["gnews"] = True
    if undated:
        item["undated"] = True
    return item


def load_archive():
    try:
        data = json.loads(ARCHIVE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def merge(archive, results, now, settings):
    by_id = {it["id"]: it for it in archive}
    by_title = {}
    for it in archive:
        key = title_key(it["title"])
        if len(key) > 24:
            by_title.setdefault(key, it)

    added = 0
    # Direct feeds first, so a publisher's own link wins over a Google News copy.
    ordered = sorted(results, key=lambda r: r[0]["kind"] != "direct")
    for feed, entries, _err, _secs in ordered:
        for entry in entries:
            item = to_item(entry, feed, now, settings["exclude"])
            if item is None:
                continue
            if item["id"] in by_id:
                continue
            key = title_key(item["title"])
            twin = by_title.get(key) if len(key) > 24 else None
            if twin and abs(twin["ts"] - item["ts"]) < 3 * 86400:
                also = twin.get("also") or []
                if item["source"] != twin["source"] and item["source"] not in also:
                    twin["also"] = (also + [item["source"]])[:6]
                continue
            by_id[item["id"]] = item
            if len(key) > 24:
                by_title[key] = item
            added += 1

    cutoff = now - int(settings["archive_days"]) * 86400
    kept = [it for it in by_id.values() if it["ts"] >= cutoff]
    kept.sort(key=lambda it: it["ts"], reverse=True)
    return kept, added


# ---------------------------------------------------------------- rendering

def e(text):
    return html.escape(str(text), quote=True)


def split_display(item):
    """Return (host, path) for the link line under the headline."""
    if item.get("via") and "news.google.com" in item["link"]:
        host = item.get("home") or "news.google.com"
        return host, " · via Google News"
    parts = urlsplit(item["link"])
    host = parts.netloc.removeprefix("www.")
    path = parts.path if parts.path not in ("", "/") else ""
    if parts.query:
        path += "?" + parts.query
    return host, path


PAGE_CSS = """
:root{--bg:#f5f4f0;--card:#ffffff;--ink:#15171c;--muted:#5b616c;--faint:#8b919b;
--line:#e2e0da;--link:#1f4fd1;--chip:#ebe9e4;--focus:#1f4fd1;--soft:#f3f1ec;--warn:#9a5b00}
@media (prefers-color-scheme:dark){:root{--bg:#101215;--card:#191c21;--ink:#e8e9ec;
--muted:#a2a8b2;--faint:#737a86;--line:#2a2e35;--link:#8fb3ff;--chip:#22262c;--focus:#8fb3ff;
--soft:#14171b;--warn:#f0b35a}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
button{font-family:inherit}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px 96px}
.top{position:sticky;top:0;z-index:5;background:var(--bg);padding:14px 0 10px;
border-bottom:1px solid var(--line)}
.top-row{display:flex;align-items:center;justify-content:space-between;gap:12px}
.top-right{display:flex;align-items:center;gap:10px}
h1{font-size:20px;margin:0;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:12.5px;margin-top:2px}
.sub a{color:var(--muted)}
.controls{display:flex;flex-direction:column;gap:8px;margin-top:10px}
input[type=search],input[type=text]{width:100%;font:inherit;font-size:15px;padding:9px 12px;
border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink)}
input[type=search]:focus,input[type=text]:focus{outline:2px solid var(--focus);outline-offset:1px}
.chips{display:flex;gap:6px;overflow-x:auto;padding-bottom:2px;scrollbar-width:none;
-webkit-overflow-scrolling:touch}
.chips::-webkit-scrollbar{display:none}
.chip{flex:none;border:1px solid var(--line);background:var(--chip);color:var(--ink);
border-radius:999px;padding:5px 11px;font-size:13px;line-height:1.2;cursor:pointer;white-space:nowrap}
.chip .dot{display:inline-block;width:8px;height:8px;border-radius:50%;
background:var(--beat);margin-right:6px;vertical-align:1px}
.chip .n{opacity:.6;margin-left:4px;font-variant-numeric:tabular-nums}
.chip[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
h2.day{font-size:12.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
margin:26px 0 10px;font-weight:650}
.item{background:var(--card);border:1px solid var(--line);
border-left:4px solid var(--beat);border-radius:10px;padding:12px 14px 11px;margin:0 0 12px}
.title{margin:0;font-size:17px;line-height:1.3;font-weight:650;letter-spacing:-.005em}
.title a{color:var(--ink);text-decoration:none}
.title a:hover,.title a:focus{text-decoration:underline}
.link{display:flex;align-items:center;gap:8px;margin-top:5px}
.url{display:flex;min-width:0;flex:1;align-items:baseline;color:var(--link);text-decoration:none;
font:13px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.url:hover .host,.url:focus .host{text-decoration:underline}
.arrow{flex:none;color:var(--faint);margin-right:6px}
.host{flex:0 1 auto;max-width:70%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
.path{flex:1 1 0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;opacity:.72}
.copy,.act{flex:none;font-size:12px;line-height:1;border:1px solid var(--line);background:transparent;
color:var(--muted);border-radius:6px;padding:5px 8px;cursor:pointer;text-decoration:none;white-space:nowrap}
.copy:hover,.act:hover{color:var(--ink);border-color:var(--muted)}
.act.on{color:var(--ink);border-color:var(--ink);font-weight:600}
.act.primary{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.meta{margin-top:7px;font-size:12.5px;color:var(--muted);display:flex;flex-wrap:wrap;
align-items:center;gap:4px 6px}
.meta .beat{color:var(--beat);font-weight:600}
.meta .also{color:var(--faint)}
.acts{margin-left:auto;display:flex;gap:6px}
.cite{margin-top:10px;padding:10px 12px;background:var(--soft);border:1px solid var(--line);border-radius:8px}
.cite-label{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-weight:650}
.fn{margin:4px 0 0;font:14px/1.5 Georgia,"Times New Roman",serif;overflow-wrap:anywhere}
.checks{margin:8px 0 0;padding-left:18px;font-size:12.5px;color:var(--warn)}
.checks li{margin:2px 0}
.cite-actions{display:flex;gap:6px;margin-top:9px;flex-wrap:wrap}
.empty{color:var(--muted);text-align:center;padding:48px 0}
footer{color:var(--faint);font-size:12px;margin-top:32px;text-align:center}
footer a{color:var(--faint)}
.listbar{position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:10;display:flex;
align-items:center;gap:10px;background:var(--ink);color:var(--bg);border-radius:999px;
padding:8px 8px 8px 16px;box-shadow:0 6px 24px rgba(0,0,0,.25);font-size:14px;white-space:nowrap}
.listbar button{border:0;border-radius:999px;background:var(--bg);color:var(--ink);font-size:13px;
font-weight:600;padding:7px 12px;cursor:pointer}
.panel{position:fixed;inset:0;z-index:20;background:var(--bg);overflow-y:auto;-webkit-overflow-scrolling:touch}
.panel-inner{max-width:780px;margin:0 auto;padding:16px 16px 48px}
.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px;
padding-bottom:10px;border-bottom:1px solid var(--line)}
.panel-head h2{margin:0;font-size:19px}
.field{display:block;margin-top:14px;font-size:13px;color:var(--muted)}
.field input{margin-top:4px}
.chk{display:flex;align-items:center;gap:8px;margin-top:12px;font-size:14px}
.panel-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.panel-actions .act{font-size:13px;padding:8px 11px}
.note{font-size:12.5px;color:var(--muted);margin:12px 0 0}
.audit{margin-top:12px;font-size:13px;border:1px solid var(--line);border-radius:8px;padding:9px 12px;background:var(--card)}
.audit ul{margin:6px 0 0;padding-left:18px;color:var(--warn)}
.audit.ok{color:var(--muted)}
.litems{list-style:none;margin:16px 0 0;padding:0;counter-reset:n}
.litem{counter-increment:n;position:relative;background:var(--card);border:1px solid var(--line);
border-left:4px solid var(--beat);border-radius:10px;padding:12px 14px 11px 40px;margin:0 0 12px}
.litem::before{content:counter(n);position:absolute;left:14px;top:12px;font-weight:700;color:var(--muted);
font-variant-numeric:tabular-nums}
.ltitle{font-weight:650;font-size:16px;line-height:1.3}
.lurl{display:block;margin-top:4px;font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
color:var(--link);text-decoration:none;overflow-wrap:anywhere}
.lmeta{display:flex;flex-wrap:wrap;align-items:center;gap:4px 6px;margin-top:6px;font-size:12.5px;color:var(--muted)}
.lmeta .acts{margin-left:auto}
.lempty{color:var(--muted);text-align:center;padding:32px 0}
select{width:100%;font:inherit;font-size:15px;padding:9px 12px;border:1px solid var(--line);
border-radius:10px;background:var(--card);color:var(--ink);margin-top:4px}
.kinds{border:0;padding:0;margin:14px 0 0}
.kinds legend{font-size:13px;color:var(--muted);padding:0;margin-bottom:6px}
.radio{display:flex;gap:10px;align-items:flex-start;padding:9px 12px;border:1px solid var(--line);
border-radius:10px;background:var(--card);margin-bottom:6px;cursor:pointer;font-size:14px}
.radio input{margin-top:3px}
.radio small{display:block;color:var(--muted);font-size:12.5px;margin-top:1px}
.radio:has(input:checked){border-color:var(--ink)}
.opt{color:var(--faint)}
.more{margin-top:14px;font-size:14px}
.more summary{cursor:pointer;color:var(--muted)}
.warn{font-size:13px;color:var(--warn);margin:12px 0 0}
.yaml{margin:6px 0 0;padding:10px 12px;background:var(--card);border:1px solid var(--line);border-radius:8px;
font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--ink);white-space:pre-wrap;
overflow-wrap:anywhere}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.act[aria-disabled=true]{opacity:.45;pointer-events:none}
.edited-tag{color:var(--warn);text-transform:none;letter-spacing:0;font-weight:600}
.editor{margin-top:10px;border-top:1px solid var(--line);padding-top:4px}
.ed-grid{display:grid;grid-template-columns:1fr;gap:0 12px}
@media (min-width:640px){.ed-grid{grid-template-columns:1fr 1fr}}
.ed-field{display:block;margin-top:9px;font-size:12.5px;color:var(--muted)}
.ed-field>span:first-child{display:block;margin-bottom:3px}
.ed-field input[type=text],.ed-field textarea,.ed-field select{width:100%;font:inherit;font-size:14px;padding:7px 10px;
border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);margin:0}
.ed-field textarea{resize:vertical;min-height:2.6em;line-height:1.4}
.ed-field input:focus,.ed-field textarea:focus,.ed-field select:focus{outline:2px solid var(--focus);outline-offset:1px}
.ed-checks{display:flex;flex-wrap:wrap;gap:4px 12px}
.ed-checks label{display:inline-flex;align-items:center;gap:5px;font-size:13px;color:var(--ink)}
.ed-rating{display:flex;gap:6px}
.ed-rating select{width:auto;min-width:4.5em}
.ed-note{font-size:12px;color:var(--muted);margin:10px 0 0}
.ed-actions{display:flex;gap:6px;justify-content:flex-end;margin-top:10px}
.print-head{display:none}
[hidden]{display:none!important}
@media print{
  @page{margin:14mm 14mm 16mm}
  :root{--bg:#fff;--card:#fff;--ink:#000;--muted:#333;--faint:#555;--line:#bbb;--link:#0b3d91;--soft:#fff}
  html,body{background:#fff;color:#000}
  body{font-size:10.5pt}
  .top,.listbar,.copy,.acts,.panel-head .act,.panel-actions,.field,.chk,.note,.audit,.cite-actions,
  .checks,.editor,.edited-tag,footer,.empty,.lempty{display:none!important}
  .print-head{display:block;border-bottom:1px solid #999;padding-bottom:6px;margin-bottom:10px}
  .print-head .ph-title{font-size:15pt;font-weight:700}
  .print-head .ph-sub{font-size:9.5pt;color:#333;margin-top:2px}
  .wrap,.panel-inner{max-width:none;padding:0;margin:0}
  h2.day{margin:12px 0 6px;font-size:9pt;color:#333;break-after:avoid}
  .item,.litem{break-inside:avoid;border:none;border-left:3px solid var(--beat);border-radius:0;
    background:none;padding:2px 0 2px 10px;margin:0 0 9px;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .litem{padding-left:30px}
  .litem::before{left:10px;top:2px}
  .title,.ltitle{font-size:11pt}
  .title a{color:#000}
  .url{display:block}
  .host,.path{white-space:normal;overflow:visible;max-width:none;overflow-wrap:anywhere}
  .meta,.lmeta{margin-top:2px;font-size:9pt}
  .cite{background:none;border:none;padding:2px 0 0;margin-top:3px}
  .cite-label{display:none}
  .fn{font-size:10pt}
  body.print-list .wrap{display:none!important}
  body.print-list #listPanel{display:block!important;position:static;overflow:visible;background:#fff}
  body.print-list .panel-head{border:none;padding:0}
  body.print-list .panel-head h2{display:none}
  body.print-feed #listPanel{display:none!important}
  #addPanel{display:none!important}
}
"""

PAGE_JS = r"""
(function(){
var DATA=JSON.parse(document.getElementById('nf-data').textContent);
var CFG=JSON.parse(document.getElementById('nf-cfg').textContent);
var HAS_OSINT=typeof OSINT!=='undefined'&&OSINT&&typeof OSINT.build==='function';
var $=function(id){return document.getElementById(id)};
var items=[].slice.call(document.querySelectorAll('.item'));
var groups=[].slice.call(document.querySelectorAll('.day-group'));
var chips=[].slice.call(document.querySelectorAll('.chip'));
var q=$('q'),count=$('count'),empty=$('empty');
var beat='all';
function store(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}}

/* ---------- filtering ---------- */
function apply(){
  var terms=q.value.toLowerCase().trim().split(/\s+/).filter(Boolean),shown=0;
  items.forEach(function(el){
    var ok=(beat==='all'||el.dataset.beat===beat)&&terms.every(function(t){return el.dataset.text.indexOf(t)>-1});
    el.hidden=!ok;if(ok)shown++;
  });
  groups.forEach(function(g){g.hidden=!g.querySelector('.item:not([hidden])')});
  empty.hidden=shown>0;count.textContent=shown+(shown===1?' story':' stories');
  return shown;
}
chips.forEach(function(c){c.addEventListener('click',function(){
  beat=c.dataset.beat;chips.forEach(function(x){x.setAttribute('aria-pressed',x===c?'true':'false')});
  store('nf-beat',beat);apply();
})});
q.addEventListener('input',apply);
var saved=store('nf-beat');chips.forEach(function(c){if(c.dataset.beat===saved)c.click()});

/* ---------- times and day labels ---------- */
var now=Date.now();
document.querySelectorAll('time[data-ts]').forEach(function(t){
  var s=(now-t.dataset.ts*1000)/1000,r=null;
  if(s<3600)r=Math.max(1,Math.round(s/60))+'m ago';else if(s<86400)r=Math.round(s/3600)+'h ago';
  if(r){t.title=t.textContent;t.textContent=r;}
});
function ymd(d){return d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2)+'-'+('0'+d.getDate()).slice(-2)}
var today=ymd(new Date()),yest=ymd(new Date(now-864e5));
document.querySelectorAll('h2.day').forEach(function(h){
  if(h.dataset.date===today)h.textContent='Today · '+h.textContent;
  else if(h.dataset.date===yest)h.textContent='Yesterday · '+h.textContent;
});
var MONTHS=['January','February','March','April','May','June','July','August','September','October','November','December'];
function longDate(d){return ('0'+d.getDate()).slice(-2)+' '+MONTHS[d.getMonth()]+' '+d.getFullYear()}

/* ---------- OSINT citations ---------- */
var TEXT_KEYS=['lead','authors','editors','translators','contributors','title','titleStyle','transTitle','origLang','transBy','location','descType','descDetails','accessNote','rating','publisher','date','dateKind','accessed','url','archiveUrl','archiveDate','locator','note','shortName','shortTitle'];
var EDITS={};try{EDITS=JSON.parse(store('nf-edits')||'{}')||{}}catch(e){EDITS={}}
function saveEdits(){store('nf-edits',JSON.stringify(EDITS))}
function stateFor(it){
  var st=baseState(it),ed=EDITS[it.id];
  if(ed)Object.keys(ed).forEach(function(k){st[k]=Array.isArray(ed[k])?ed[k].slice():ed[k]});
  return st;
}
function baseState(it){
  var st={},t=it.ctype||'news';
  TEXT_KEYS.forEach(function(k){st[k]=''});
  st.type=t;st.titleStyle=t==='report'?'italics':'quotes';
  st.shortUseTitle=true;st.access=(it.access||[]).slice();st.quals=[];st.contribRole='ed';
  st.authors=(it.authors||[]).join('\n');st.title=it.title||'';
  st.location=it.location||it.source||'';st.descType=it.desc||'News Article';
  st.descDetails=it.details||'';st.publisher=it.publisher||'';
  st.date=it.date?(HAS_OSINT?OSINT.normDate(it.date).text:it.date):'';st.url=it.gnews?'':(it.link||'');
  st.dayDate=t!=='report';st.volatile=t==='social';st.live=false;st.ai=false;
  return st;
}
function ownFlags(it){
  var f=[],ed=EDITS[it.id]||{};
  if(it.gnews&&!ed.url)f.push('Google News gave only a redirect link. Open the story and add the publisher’s own URL.');
  if(!(it.authors&&it.authors.length)&&!ed.authors&&!ed.lead)f.push('The feed named no author. Check the story for a byline, or use the outlet plus Staff.');
  if(!it.date&&!ed.date)f.push('The feed gave no publication date. Take it from the story.');
  if(it.desc_default&&!('descType' in ed))f.push('Kind of source defaults to '+(it.desc||'News Article')+'. Change it if this is analysis, opinion, or another kind.');
  return f;
}
function cite(it){
  var st=stateFor(it),r=OSINT.build(st);
  var checks=r.checks.filter(function(c){return c.level!=='note'}).map(function(c){return c.msg});
  return {st:st,seg:r.seg,html:OSINT.toHTML(r.seg),md:OSINT.toMarkdown(r.seg),checks:ownFlags(it).concat(checks)};
}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function flash(b,txt){var o=b.dataset.label||b.textContent;b.dataset.label=o;b.textContent=txt;setTimeout(function(){b.textContent=o},1400)}
function copyRich(html,text,btn){
  var done=function(){flash(btn,'Copied')};
  var plain=function(){if(navigator.clipboard)navigator.clipboard.writeText(text).then(done,function(){})};
  try{
    if(window.ClipboardItem&&navigator.clipboard&&navigator.clipboard.write){
      navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([html],{type:'text/html'}),
        'text/plain':new Blob([text],{type:'text/plain'})})]).then(done,plain);return;
    }
  }catch(e){}
  plain();
}
var ACCESS_OPTS=['metered paywall','paywalled','free registration required','institutional access','region-restricted','app only'];
var FIELDS=[
  ['lead','Opening',{sel:[['','None'],['See','See'],['Cited in','Cited in'],['Quoted in','Quoted in']]}],
  ['authors','Authors, one per line',{area:1}],
  ['title','Title',{area:1}],
  ['titleStyle','Title set in',{sel:[['quotes','Quotation marks'],['italics','Italics (books, reports)'],['plain','Plain description (no title)']]}],
  ['location','Publication (location)'],
  ['descType','Kind of source',{list:'descList'}],
  ['descDetails','Details (separate with semicolons)'],
  ['quals','Qualifiers (separate with commas)',{arr:1}],
  ['access','Access',{checks:ACCESS_OPTS}],
  ['rating','Rating (reliability and credibility)',{rating:1}],
  ['publisher','Publisher'],
  ['date','Date'],
  ['url','Link'],
  ['archiveUrl','Archive link'],
  ['archiveDate','Archive captured'],
  ['locator','Locator (pages or timestamp)'],
  ['note','Commentary after the citation',{area:1}]];
function editorHTML(){
  return '<div class="ed-grid">'+FIELDS.map(function(f){
    var k=f[0],o=f[2]||{},h='<label class="ed-field" data-k="'+k+'"><span>'+esc(f[1])+'</span>';
    if(o.sel)h+='<select>'+o.sel.map(function(x){return '<option value="'+esc(x[0])+'">'+esc(x[1])+'</option>'}).join('')+'</select>';
    else if(o.area)h+='<textarea rows="2" spellcheck="false"></textarea>';
    else if(o.checks)h+='<span class="ed-checks">'+o.checks.map(function(x){return '<label><input type="checkbox" value="'+esc(x)+'"> '+esc(x)+'</label>'}).join('')+'</span>';
    else if(o.rating)h+='<span class="ed-rating"><select class="r1"><option value="">–</option>'+'ABCDEF'.split('').map(function(x){return '<option>'+x+'</option>'}).join('')+
      '</select><select class="r2"><option value="">–</option>'+'123456'.split('').map(function(x){return '<option>'+x+'</option>'}).join('')+'</select></span>';
    else h+='<input type="text" autocomplete="off" spellcheck="false"'+(o.list?' list="'+o.list+'"':'')+'>';
    return h+'</label>';
  }).join('')+'</div>';
}
function fieldEl(ed,k){return ed.querySelector('.ed-field[data-k="'+k+'"]')}
function readField(ed,f){
  var el=fieldEl(ed,f[0]),o=f[2]||{};
  if(o.checks)return [].slice.call(el.querySelectorAll('input:checked')).map(function(x){return x.value});
  if(o.rating){var a=el.querySelector('.r1').value,b=el.querySelector('.r2').value;return a&&b?a+b:''}
  var v=el.querySelector('input,textarea,select').value;
  if(o.arr)return v.split(',').map(function(x){return x.trim()}).filter(Boolean);
  return v;
}
function fillEditor(ed,st){
  FIELDS.forEach(function(f){
    var el=fieldEl(ed,f[0]),o=f[2]||{},v=st[f[0]];
    if(o.checks){var on=(v||[]);[].slice.call(el.querySelectorAll('input')).forEach(function(x){x.checked=on.indexOf(x.value)>-1})}
    else if(o.rating){v=/^[A-F][1-6]$/.test(v||'')?v:'';el.querySelector('.r1').value=v?v[0]:'';el.querySelector('.r2').value=v?v[1]:''}
    else el.querySelector('input,textarea,select').value=o.arr?(v||[]).join(', '):(v||'');
  });
}
function sameVal(a,b){return JSON.stringify(a==null?'':a)===JSON.stringify(b==null?'':b)}
var MOUNTS=[];
function refreshAll(id){
  MOUNTS=MOUNTS.filter(function(m){return m.box.isConnected});
  MOUNTS.forEach(function(m){if(m.id===id)m.refresh()});
  if(!$('listPanel').hidden)renderAudit();
}
function mountCite(box,it){
  box.innerHTML='<div class="cite-label">OSINT citation<span class="edited-tag" hidden> · edited</span></div>'+
    '<p class="fn"></p><ul class="checks"></ul>'+
    '<div class="cite-actions"><button class="act c-copy" type="button">Copy citation</button>'+
    '<button class="act c-short" type="button">Copy short form</button>'+
    '<button class="act c-edit" type="button" aria-expanded="false">Edit</button>'+
    '<a class="act" href="'+esc(CFG.generator)+'" target="_blank" rel="noopener">OSINT Cites ↗</a></div>'+
    '<div class="editor" hidden>'+editorHTML()+
    '<p class="ed-note">Changes are saved in this browser and carry into your list, Print / PDF, Copy all citations and the OSINT Cites export.</p>'+
    '<div class="ed-actions"><button class="act c-reset" type="button">Reset to feed data</button>'+
    '<button class="act primary c-done" type="button">Done</button></div></div>';
  var ed=box.querySelector('.editor'),eb=box.querySelector('.c-edit');
  function refresh(){
    var c=cite(it),ul=box.querySelector('.checks');
    box.querySelector('.fn').innerHTML=c.html;
    ul.innerHTML=c.checks.map(function(m){return '<li>'+esc(m)+'</li>'}).join('');ul.hidden=!c.checks.length;
    box.querySelector('.edited-tag').hidden=!EDITS[it.id];
  }
  function setOpen(open){ed.hidden=!open;eb.classList.toggle('on',open);eb.setAttribute('aria-expanded',open?'true':'false');
    if(open){fillEditor(ed,stateFor(it));var first=ed.querySelector('textarea,input');if(first)first.focus()}}
  function changed(){
    var base=baseState(it),cur={};
    FIELDS.forEach(function(f){var v=readField(ed,f),b=base[f[0]];
      if(f[2]&&f[2].rating)b=/^[A-F][1-6]$/.test(b||'')?b:'';
      if(!sameVal(v,b))cur[f[0]]=v});
    if(Object.keys(cur).length)EDITS[it.id]=cur;else delete EDITS[it.id];
    saveEdits();refreshAll(it.id);
  }
  ed.addEventListener('input',changed);ed.addEventListener('change',changed);
  box.querySelector('.c-copy').addEventListener('click',function(ev){var c=cite(it);copyRich(c.html,c.md,ev.currentTarget)});
  box.querySelector('.c-short').addEventListener('click',function(ev){var sf=OSINT.shortForms(stateFor(it)).short;
    copyRich(OSINT.toHTML(sf),OSINT.toMarkdown(sf),ev.currentTarget)});
  eb.addEventListener('click',function(){setOpen(ed.hidden)});
  box.querySelector('.c-done').addEventListener('click',function(){setOpen(false)});
  box.querySelector('.c-reset').addEventListener('click',function(){delete EDITS[it.id];saveEdits();fillEditor(ed,stateFor(it));refreshAll(it.id)});
  MOUNTS.push({id:it.id,box:box,refresh:refresh});refresh();
}
if(!HAS_OSINT){document.querySelectorAll('.cite-btn').forEach(function(b){b.hidden=true});$('withCitesRow').hidden=true;
  ['copyCites','exportList'].forEach(function(id){$(id).hidden=true});}

/* ---------- source list ---------- */
var LIST=[];try{LIST=JSON.parse(store('nf-list')||'[]')||[]}catch(e){LIST=[]}
var listName=$('listName'),withCites=$('withCites');
listName.value=store('nf-list-name')||'';
withCites.checked=store('nf-with-cites')!=='0';
function inList(id){return LIST.some(function(x){return x.id===id})}
function saveList(){store('nf-list',JSON.stringify(LIST));sync()}
function sync(){
  $('listbar').hidden=!LIST.length||!$('listPanel').hidden;
  $('listCount').textContent=LIST.length+(LIST.length===1?' story in your list':' stories in your list');
  items.forEach(function(el){var b=el.querySelector('.add-btn'),on=inList(DATA[el.dataset.i].id);
    b.classList.toggle('on',on);b.textContent=on?'In list ✓':'+ List';b.setAttribute('aria-pressed',on?'true':'false')});
}
function renderList(){
  var ol=$('listItems'),cites=withCites.checked&&HAS_OSINT;
  $('listHead').textContent='Source list ('+LIST.length+')';
  ol.innerHTML='';
  $('listEmpty').hidden=LIST.length>0;
  LIST.forEach(function(it,n){
    var li=document.createElement('li');li.className='litem';li.style.setProperty('--beat',it.color||'#8b919b');
    var when=it.date?longDate(new Date(it.date+'T12:00:00')):'';
    li.innerHTML='<div class="ltitle"></div><a class="lurl" target="_blank" rel="noopener"></a>'+
      '<div class="lmeta"><span class="lsrc"></span><span>·</span><span class="lbeat"></span>'+(when?'<span>·</span><span>'+esc(when)+'</span>':'')+
      '<span class="acts"><button class="act up" type="button" aria-label="Move up">↑</button>'+
      '<button class="act rm" type="button">Remove</button></span></div>'+
      (cites?'<div class="cite"></div>':'');
    li.querySelector('.ltitle').textContent=it.title;
    var a=li.querySelector('.lurl');a.href=it.link;a.textContent=it.gnews?(it.home||'news.google.com')+' · via Google News':it.link.replace(/^https?:\/\//,'');
    li.querySelector('.lsrc').textContent=it.source;li.querySelector('.lbeat').textContent=it.beat;
    li.querySelector('.rm').addEventListener('click',function(){LIST.splice(n,1);saveList();renderList()});
    var up=li.querySelector('.up');if(n===0)up.hidden=true;
    up.addEventListener('click',function(){var x=LIST.splice(n,1)[0];LIST.splice(n-1,0,x);saveList();renderList()});
    if(cites)mountCite(li.querySelector('.cite'),it);
    ol.appendChild(li);
  });
  renderAudit();
}
function renderAudit(){
  var au=$('audit'),cites=withCites.checked&&HAS_OSINT;
  if(cites&&LIST.length){
    var res=OSINT.auditList(LIST.map(stateFor)),own=0;
    LIST.forEach(function(it){if(ownFlags(it).length)own++});
    var rows=res.rows.map(function(r){return '<li>Source '+(r.nums?r.nums.join(', '):r.n)+': '+esc(r.msg)+'</li>'});
    au.className='audit'+(rows.length||own?'':' ok');
    au.innerHTML=(own?'<strong>'+own+' of '+LIST.length+'</strong> sources have details to fill in from the story itself (listed under each).':'No feed gaps found.')+
      (rows.length?'<div style="margin-top:6px">The OSINT Cites audit also flags:</div><ul>'+rows.join('')+'</ul>':'');
    au.hidden=false;
  }else au.hidden=true;
}
function openList(){$('listPanel').hidden=false;document.body.style.overflow='hidden';renderList();sync();$('closeList').focus()}
function closeList(){$('listPanel').hidden=true;document.body.style.overflow='';sync()}
$('openList').addEventListener('click',openList);
$('closeList').addEventListener('click',closeList);
document.addEventListener('keydown',function(ev){if(ev.key==='Escape'&&!$('listPanel').hidden)closeList()});
listName.addEventListener('input',function(){store('nf-list-name',listName.value)});
withCites.addEventListener('change',function(){store('nf-with-cites',withCites.checked?'1':'0');renderList()});
$('clearList').addEventListener('click',function(){if(LIST.length&&confirm('Remove all '+LIST.length+' stories from the list?')){LIST=[];saveList();renderList()}});
$('copyCites').addEventListener('click',function(ev){
  if(!LIST.length)return;
  var cs=LIST.map(cite);
  copyRich('<ol>'+cs.map(function(c){return '<li>'+c.html+'</li>'}).join('')+'</ol>',
    cs.map(function(c,n){return (n+1)+'. '+c.md}).join('\n'),ev.currentTarget);
});
function fileSlug(s){return String(s).toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')}
$('exportList').addEventListener('click',function(){
  if(!LIST.length)return;
  var name=listName.value.trim();
  var text=OSINT.listFile(name,LIST.map(function(it,n){return {id:'s'+(n+1),st:stateFor(it)}}));
  var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type:'application/json'}));
  a.download=(fileSlug(name)||'source-list')+'.json';document.body.appendChild(a);a.click();
  setTimeout(function(){URL.revokeObjectURL(a.href);a.remove()},1500);
});

/* ---------- printing ---------- */
function printNow(mode){
  var stamp=longDate(new Date())+', '+new Date().toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});
  var title,sub;
  if(mode==='list'){
    var nm=listName.value.trim();
    title=nm||'Source list';
    sub=LIST.length+(LIST.length===1?' source':' sources')+' · printed '+stamp+(withCites.checked&&HAS_OSINT?' · citations in OSINT Style Guide form, unverified until checked against each source':'');
  }else{
    var b=chips.filter(function(c){return c.getAttribute('aria-pressed')==='true'})[0];
    var label=b&&b.dataset.beat!=='all'?b.textContent.replace(/\d+$/,'').trim():'';
    title=CFG.title+(label?' — '+label:'');
    sub=apply()+' stories'+(q.value.trim()?' matching “'+q.value.trim()+'”':'')+' · printed '+stamp;
  }
  var ph=$('printHead');ph.querySelector('.ph-title').textContent=title;ph.querySelector('.ph-sub').textContent=sub;
  document.body.classList.remove('print-list','print-feed');document.body.classList.add('print-'+mode);
  var old=document.title;document.title=title+' — '+longDate(new Date());
  var done=function(){document.title=old;window.removeEventListener('afterprint',done)};
  window.addEventListener('afterprint',done);
  window.print();
}
$('printFeed').addEventListener('click',function(){printNow('feed')});
$('printList').addEventListener('click',function(){if(LIST.length)printNow('list')});

/* ---------- add a source ---------- */
var addPanel=$('addPanel'),srcKind='url';
var srcValue=$('srcValue'),srcName=$('srcName'),srcBeat=$('srcBeat'),srcNewBeat=$('srcNewBeat');
var KIND_TEXT={
  url:['Address','https://example.com, or its RSS link'],
  site:['Domain','csis.org'],
  query:['Search','"Taiwan Strait" OR "South China Sea"']};
(CFG.beats||[]).forEach(function(b){var o=document.createElement('option');o.value=b;o.textContent=b;srcBeat.appendChild(o)});
var nb=document.createElement('option');nb.value='__new';nb.textContent='New beat…';srcBeat.appendChild(nb);
function srcNormalize(){
  var v=srcValue.value.trim();
  if(!v)return '';
  if(srcKind==='url'){
    if(!/^https?:\/\//i.test(v))v='https://'+v;
    try{
      var u=new URL(v),h=u.hostname.replace(/^www\./,''),m;
      ['utm_source','utm_medium','utm_campaign','utm_content','utm_term','ref','s'].forEach(function(k){u.searchParams.delete(k)});
      v=u.toString();
      if(/(^|\.)reddit\.com$/.test(h)&&(m=u.pathname.match(/^\/r\/([^\/]+)/)))v='https://www.reddit.com/r/'+m[1]+'/.rss';
      else if(/\.substack\.com$/.test(h)&&!/\/feed\/?$/.test(u.pathname))v=u.origin+'/feed';
    }catch(e){}
  }else if(srcKind==='site'){
    v=v.replace(/^https?:\/\//i,'').replace(/^www\./i,'').replace(/[\/?#].*$/,'').toLowerCase();
  }
  return v;
}
function yq(x){return JSON.stringify(String(x))}
function srcBuild(){
  var v=srcNormalize(),name=srcName.value.trim();
  var beat=srcBeat.value==='__new'?srcNewBeat.value.trim():srcBeat.value;
  var loc=$('srcLocation').value.trim(),desc=$('srcDesc').value.trim(),acc=$('srcAccess').value;
  var fields=[];
  if(name)fields.push('name: '+yq(name));
  fields.push(srcKind+': '+yq(v));
  if(loc)fields.push('location: '+yq(loc));
  if(desc)fields.push('desc: '+yq(desc));
  if(acc)fields.push('access: ['+yq(acc)+']');
  var yaml='# Added from WOPR, '+longDate(new Date())+'\nbeat: '+yq(beat)+'\nsources:\n  - '+fields.join('\n    ')+'\n';
  var base=ymd(new Date())+'-'+(fileSlug(name||v.replace(/^https?:\/\//,''))||'source').slice(0,48)+'.yaml';
  $('srcFile').textContent='sources/'+base;$('srcYaml').textContent=yaml;
  var problem='';
  if(!v)problem='Enter the '+KIND_TEXT[srcKind][0].toLowerCase()+' to add.';
  else if(srcKind==='url'){try{var u=new URL(v);if(u.hostname.indexOf('.')<0)problem='That doesn’t look like a web address.'}catch(e){problem='That doesn’t look like a web address.'}}
  else if(srcKind==='site'&&v.indexOf('.')<0)problem='Give a domain such as csis.org.';
  if(!problem&&!beat)problem='Name the new beat.';
  var dup=null,key=v.toLowerCase().replace(/\/+$/,'');
  (CFG.sources||[]).forEach(function(x){var o=x[srcKind];if(o&&String(o).toLowerCase().replace(/\/+$/,'')===key)dup=x});
  var w=$('srcWarn');
  if(dup){w.textContent='Already in the feed as “'+dup.name+'” under '+dup.beat+'.';w.hidden=false}
  else if(problem&&srcValue.value.trim()){w.textContent=problem;w.hidden=false}
  else w.hidden=true;
  var gh=$('srcGithub'),ok=!problem&&!dup;
  if(CFG.repo){
    gh.hidden=false;
    gh.href='https://github.com/'+CFG.repo+'/new/'+encodeURIComponent(CFG.branch||'main')+'/sources?filename='+
      encodeURIComponent(base)+'&value='+encodeURIComponent(yaml);
    gh.setAttribute('aria-disabled',ok?'false':'true');
    $('srcHow').innerHTML='GitHub opens with this file filled in. Tap <em>Commit changes</em> and the feed rebuilds with the new source in a few minutes; check <a href="status.html">source status</a> afterward to see that it worked. To remove a source later, delete its file in the <code>sources</code> folder.';
  }else{
    gh.hidden=true;
    $('srcHow').innerHTML='This page doesn’t know which GitHub repository it comes from, so copy the YAML and save it as a new file in the <code>sources</code> folder, or add <code>repo: your-name/newsfeed</code> under settings in feeds.yaml.';
  }
  return {yaml:yaml,ok:ok};
}
[].slice.call(document.querySelectorAll('input[name=srcKind]')).forEach(function(r){r.addEventListener('change',function(){
  srcKind=r.value;$('srcValueLabel').textContent=KIND_TEXT[srcKind][0];srcValue.placeholder=KIND_TEXT[srcKind][1];
  srcValue.inputMode=srcKind==='url'?'url':'text';srcBuild();
})});
srcValue.placeholder=KIND_TEXT.url[1];srcValue.inputMode='url';
srcBeat.addEventListener('change',function(){$('srcNewBeatRow').hidden=srcBeat.value!=='__new';srcBuild()});
['srcValue','srcName','srcNewBeat','srcLocation','srcDesc'].forEach(function(id){$(id).addEventListener('input',srcBuild)});
$('srcAccess').addEventListener('change',srcBuild);
srcValue.addEventListener('blur',function(){var v=srcNormalize();if(v&&v!==srcValue.value.trim()){srcValue.value=v;srcBuild()}});
$('srcCopy').addEventListener('click',function(ev){var r=srcBuild();
  if(navigator.clipboard)navigator.clipboard.writeText(r.yaml).then(function(){flash(ev.currentTarget,'Copied')},function(){})});
function openAdd(){
  var cur=chips.filter(function(c){return c.getAttribute('aria-pressed')==='true'})[0];
  if(cur&&cur.dataset.beat!=='all'){var t=cur.textContent.replace(/\d+$/,'').trim();for(var i=0;i<srcBeat.options.length;i++)if(srcBeat.options[i].value===t)srcBeat.selectedIndex=i}
  addPanel.hidden=false;document.body.style.overflow='hidden';srcBuild();srcValue.focus();
}
function closeAdd(){addPanel.hidden=true;document.body.style.overflow=''}
$('srcGithub').addEventListener('click',function(){
  // after handing the file to GitHub, clear the form for the next source
  setTimeout(function(){['srcValue','srcName','srcNewBeat','srcLocation','srcDesc'].forEach(function(id){$(id).value=''});
    $('srcAccess').value='';srcBuild();},800);
});
$('openAdd').addEventListener('click',openAdd);
$('closeAdd').addEventListener('click',closeAdd);
document.addEventListener('keydown',function(ev){if(ev.key==='Escape'&&!addPanel.hidden)closeAdd()});

/* ---------- card buttons ---------- */
document.addEventListener('click',function(ev){
  var b=ev.target.closest('button');if(!b)return;
  if(b.classList.contains('copy')){
    if(navigator.clipboard)navigator.clipboard.writeText(b.dataset.url).then(function(){flash(b,'Copied')},function(){});
    return;
  }
  var card=b.closest('.item');if(!card)return;
  var it=DATA[card.dataset.i];
  if(b.classList.contains('add-btn')){
    if(inList(it.id))LIST=LIST.filter(function(x){return x.id!==it.id});
    else{var copy=JSON.parse(JSON.stringify(it));copy.color=card.style.getPropertyValue('--beat').trim();LIST.push(copy)}
    saveList();
  }else if(b.classList.contains('cite-btn')){
    var p=card.querySelector('.cite');
    if(p){p.hidden=!p.hidden}else{p=document.createElement('div');p.className='cite';card.appendChild(p);mountCite(p,it)}
    b.classList.toggle('on',!p.hidden);
  }
});

sync();apply();
})();
"""


def render_item(item, i, colors, tz):
    host, path = split_display(item)
    dt = datetime.fromtimestamp(item["ts"], tz)
    when = dt.strftime("%b %-d, %-I:%M %p %Z")
    also = ""
    if item.get("also"):
        also = f'<span class="also">· also: {e(", ".join(item["also"]))}</span>'
    beat_slug = slug(item["beat"])
    text = f'{item["title"]} {item["source"]} {host} {" ".join(item.get("also") or [])}'.lower()
    link = e(item["link"])
    return (
        f'<article class="item" style="--beat:{colors[item["beat"]]}" data-i="{i}" '
        f'data-beat="{beat_slug}" data-text="{e(text)}">'
        f'<h3 class="title"><a href="{link}" target="_blank" rel="noopener">{e(item["title"])}</a></h3>'
        f'<div class="link"><a class="url" href="{link}" target="_blank" rel="noopener" title="{link}">'
        f'<span class="arrow" aria-hidden="true">↳</span>'
        f'<span class="host">{e(host)}</span><span class="path">{e(path)}</span></a>'
        f'<button class="copy" type="button" data-url="{link}" aria-label="Copy link">Copy</button></div>'
        f'<div class="meta"><span class="src">{e(item["source"])}</span>'
        f'<span>·</span><span class="beat">{e(item["beat"])}</span>'
        f'<span>·</span><time datetime="{dt.isoformat()}" data-ts="{item["ts"]}">{e(when)}</time>'
        f'{also}<span class="acts"><button class="act cite-btn" type="button">Cite</button>'
        f'<button class="act add-btn" type="button" aria-pressed="false">+ List</button></span>'
        f'</div></article>'
    )


DATA_KEYS = ("id", "title", "link", "source", "beat", "home", "authors", "location", "desc",
             "desc_default", "ctype", "details", "publisher", "access", "gnews")


def page_record(item, tz):
    rec = {k: item[k] for k in DATA_KEYS if item.get(k) not in (None, "", [], False)}
    rec.setdefault("ctype", "news")
    if "desc" not in item:  # stories archived before citations were added
        rec["desc_default"] = True
    if not item.get("undated"):
        rec["date"] = datetime.fromtimestamp(item["ts"], tz).strftime("%Y-%m-%d")
    return rec


def json_for_script(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_page(items, beats, settings, built_at, feeds, n_ok, banner=""):
    n_sources = len(feeds)
    tz = ZoneInfo(settings["timezone"])
    colors = {b: PALETTE[i % len(PALETTE)] for i, b in enumerate(beats)}
    for it in items:  # beats that disappeared from config but remain in the archive
        colors.setdefault(it["beat"], "#8b919b")

    counts = {}
    for it in items:
        counts[it["beat"]] = counts.get(it["beat"], 0) + 1
    chips = [f'<button class="chip" type="button" data-beat="all" aria-pressed="true">'
             f'All<span class="n">{len(items)}</span></button>']
    for b in beats:
        if counts.get(b):
            chips.append(
                f'<button class="chip" type="button" data-beat="{slug(b)}" aria-pressed="false" '
                f'style="--beat:{colors[b]}"><span class="dot"></span>{e(b)}'
                f'<span class="n">{counts[b]}</span></button>'
            )

    body, current_day = [], None
    for i, it in enumerate(items):
        day = datetime.fromtimestamp(it["ts"], tz).date()
        if day != current_day:
            if current_day is not None:
                body.append("</section>")
            body.append(f'<section class="day-group"><h2 class="day" data-date="{day.isoformat()}">'
                        f'{e(day.strftime("%A, %B %-d"))}</h2>')
            current_day = day
        body.append(render_item(it, i, colors, tz))
    if current_day is not None:
        body.append("</section>")

    data = json_for_script([page_record(it, tz) for it in items])
    cfg = json_for_script({
        "title": settings["title"], "generator": settings["osint_generator"],
        "repo": settings.get("repo") or "", "branch": settings.get("branch") or "main",
        "beats": beats,
        "sources": [{"name": f["name"], "beat": f["beat"], **f["spec"]} for f in feeds],
    })
    desc_options = "".join(f'<option value="{e(d)}"></option>' for d in DESC_SUGGESTIONS)
    built = datetime.fromtimestamp(built_at, tz).strftime("%a %b %-d, %-I:%M %p %Z")
    title = e(settings["title"])
    gen = e(settings["osint_generator"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{title}</title>
<link rel="alternate" type="application/rss+xml" title="{title}" href="feed.xml">
<style>{PAGE_CSS}</style></head>
<body>
<div class="print-head" id="printHead"><div class="ph-title"></div><div class="ph-sub"></div></div>
<div class="wrap">
<header class="top">
  <div class="top-row"><h1>{title}</h1>
    <div class="top-right"><span class="sub" id="count"></span>
    <button class="act" type="button" id="openAdd" title="Add a new source to the feed">+ Source</button>
    <button class="act" type="button" id="printFeed" title="Print or save as PDF the stories now shown">Print / PDF</button></div></div>
  <div class="sub">Updated {e(built)} · {n_ok}/{n_sources} sources responded ·
    <a href="status.html">source status</a> · <a href="feed.xml">RSS</a></div>
  {banner}
  <div class="controls">
    <input id="q" type="search" placeholder="Filter headlines, sources, sites…" autocomplete="off">
    <nav class="chips" aria-label="Beats">{''.join(chips)}</nav>
  </div>
</header>
<main>{''.join(body)}
<p class="empty" id="empty" hidden>No stories match.</p></main>
<footer>Stories from the last {settings['page_hours']} hours · citations formatted by
  <a href="{gen}" target="_blank" rel="noopener">OSINT Cites</a></footer>
</div>

<div class="listbar" id="listbar" hidden><span id="listCount"></span>
  <button type="button" id="openList">View list</button></div>

<section class="panel" id="addPanel" hidden aria-label="Add a source">
 <div class="panel-inner">
  <div class="panel-head"><h2>Add a source</h2>
    <button class="act" type="button" id="closeAdd">Close</button></div>
  <fieldset class="kinds"><legend>What are you adding?</legend>
    <label class="radio"><input type="radio" name="srcKind" value="url" checked><span><strong>A website or feed</strong>
      <small>Paste the site's address or its RSS link. Substack, YouTube channels, Reddit and most blogs work.</small></span></label>
    <label class="radio"><input type="radio" name="srcKind" value="site"><span><strong>A site with no feed</strong>
      <small>Pulled through Google News by its domain, such as csis.org.</small></span></label>
    <label class="radio"><input type="radio" name="srcKind" value="query"><span><strong>A Google News search</strong>
      <small>Anything you'd type into Google News, such as "Taiwan Strait" or drone OR counter-UAS.</small></span></label>
  </fieldset>
  <label class="field"><span id="srcValueLabel">Address</span>
    <input type="text" id="srcValue" autocomplete="off" autocapitalize="off" spellcheck="false"></label>
  <label class="field">Name shown on the page <span class="opt">(optional for searches)</span>
    <input type="text" id="srcName" autocomplete="off"></label>
  <label class="field">Beat<select id="srcBeat"></select></label>
  <label class="field" id="srcNewBeatRow" hidden>New beat name<input type="text" id="srcNewBeat" autocomplete="off"></label>
  <details class="more"><summary>Citation details (optional)</summary>
    <label class="field">Publication name for citations
      <input type="text" id="srcLocation" placeholder="Defaults to the name above" autocomplete="off"></label>
    <label class="field">Kind of source
      <input type="text" id="srcDesc" list="descList" placeholder="News Article" autocomplete="off"></label>
    <label class="field">Access<select id="srcAccess"><option value="">Free to read</option>
      <option>metered paywall</option><option>paywalled</option><option>free registration required</option>
      <option>institutional access</option></select></label>
  </details>
  <p class="warn" id="srcWarn" hidden></p>
  <div class="field">Saved as <code id="srcFile"></code><pre class="yaml" id="srcYaml"></pre></div>
  <div class="panel-actions">
    <a class="act primary" id="srcGithub" target="_blank" rel="noopener" href="#">Add on GitHub ↗</a>
    <button class="act" type="button" id="srcCopy">Copy YAML</button>
  </div>
  <p class="note" id="srcHow"></p>
 </div>
</section>

<section class="panel" id="listPanel" hidden aria-label="Source list">
 <div class="panel-inner">
  <div class="panel-head"><h2 id="listHead">Source list</h2>
    <button class="act" type="button" id="closeList">Close</button></div>
  <label class="field">Name of the piece (optional; used for the PDF and export)
    <input type="text" id="listName" placeholder="e.g. WOPR issue 3"></label>
  <label class="chk" id="withCitesRow"><input type="checkbox" id="withCites" checked> Include OSINT citations</label>
  <div class="panel-actions">
    <button class="act primary" type="button" id="printList">Print / PDF</button>
    <button class="act" type="button" id="copyCites">Copy all citations</button>
    <button class="act" type="button" id="exportList">Export for OSINT Cites</button>
    <a class="act" href="{gen}" target="_blank" rel="noopener">Open OSINT Cites ↗</a>
    <button class="act" type="button" id="clearList">Clear list</button>
  </div>
  <p class="note">Citations are built from what each feed supplies, so treat them as unverified until
    checked against the source. The export opens in OSINT Cites with <em>Open a list file</em>,
    where <em>Audit the list</em> runs the full checks.</p>
  <div class="audit" id="audit" hidden></div>
  <ol class="litems" id="listItems"></ol>
  <p class="lempty" id="listEmpty">No stories yet. Tap <strong>+ List</strong> on any story to add it.</p>
 </div>
</section>

<datalist id="descList">{desc_options}</datalist>
<script id="nf-data" type="application/json">{data}</script>
<script id="nf-cfg" type="application/json">{cfg}</script>
<script src="osint-core.js"></script>
<script>{PAGE_JS}</script></body></html>
"""


def render_status(results, settings, built_at, core_from):
    tz = ZoneInfo(settings["timezone"])
    rows = sorted(results, key=lambda r: (r[2] is None, r[0]["beat"], r[0]["name"]))
    ok = sum(1 for r in results if r[2] is None)
    trs = []
    for feed, entries, err, secs in rows:
        state = "ok" if err is None else "fail"
        label = f"{len(entries)} items" if err is None else e(err)
        if err is None and feed.get("discovered"):
            label += f' · feed found at <a href="{e(feed["discovered"])}">{e(feed["discovered"])}</a>'
        added = f' <span class="tag">added: {e(feed["added_in"])}</span>' if feed.get("added_in") else ""
        if err is None and not entries:
            state, label = "empty", "responded, 0 items"
        kind = {"direct": "feed", "gnews-site": "Google News (site)",
                "gnews-query": "Google News (search)"}[feed["kind"]]
        trs.append(
            f'<tr class="{state}"><td>{e(feed["beat"])}</td><td>{e(feed["name"])}{added}</td>'
            f'<td>{kind}</td><td class="st">{label}</td><td>{secs:.1f}s</td>'
            f'<td><a href="{e(feed["url"])}">url</a></td></tr>'
        )
    built = datetime.fromtimestamp(built_at, tz).strftime("%a %b %-d, %-I:%M %p %Z")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>Source status</title>
<style>{PAGE_CSS}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:16px}}
th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:600}}
td a{{color:var(--link)}}
.tag{{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 4px;white-space:nowrap}}
tr.fail .st{{color:#dc2626}} tr.empty .st{{color:#d97706}} tr.ok .st{{color:var(--muted)}}
.scroll{{overflow-x:auto}}
</style></head><body><div class="wrap">
<header class="top"><div class="top-row"><h1>Source status</h1></div>
<div class="sub">Last run {e(built)} · {ok}/{len(results)} responded · citation formatter: {e(core_from)} ·
<a href="index.html">back to feed</a></div></header>
<p class="sub" style="margin-top:14px">Failures are listed first. A source that fails every run
probably moved its feed; fix or remove it in <code>feeds.yaml</code>.</p>
<div class="scroll"><table><thead><tr><th>Beat</th><th>Source</th><th>Type</th><th>Result</th>
<th>Time</th><th></th></tr></thead><tbody>{''.join(trs)}</tbody></table></div>
</div></body></html>"""


def render_rss(items, settings, built_at):
    entries = []
    for it in items:
        entries.append(
            "<item>"
            f"<title>{xml_escape(it['title'])}</title>"
            f"<link>{xml_escape(it['link'])}</link>"
            f"<guid isPermaLink=\"false\">{xml_escape(it['id'])}</guid>"
            f"<pubDate>{formatdate(it['ts'], usegmt=True)}</pubDate>"
            f"<source url={quoteattr(it['link'])}>{xml_escape(it['source'])}</source>"
            f"<category>{xml_escape(it['beat'])}</category>"
            "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        f"<title>{xml_escape(settings['title'])}</title><link>index.html</link>"
        "<description>Combined newsfeed</description>"
        f"<lastBuildDate>{formatdate(built_at, usegmt=True)}</lastBuildDate>"
        + "".join(entries)
        + "</channel></rss>\n"
    )


# ---------------------------------------------------------------- main

def write_step_summary(results):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    failed = [r for r in results if r[2] is not None]
    lines = [f"### Newsfeed build: {len(results) - len(failed)}/{len(results)} sources responded\n"]
    if failed:
        lines.append("| Source | Beat | Error |\n|---|---|---|")
        for feed, _, err, _ in failed:
            lines.append(f"| {feed['name']} | {feed['beat']} | {err.replace('|', '/')} |")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main():
    settings, feeds, beats = load_config()
    now = int(time.time())
    print(f"Fetching {len(feeds)} sources…")
    results = fetch_all(feeds, settings)
    ok = sum(1 for r in results if r[2] is None)
    for feed, entries, err, _ in results:
        if err:
            print(f"  ✗ {feed['name']} ({feed['beat']}): {err}")

    archive, added = merge(load_archive(), results, now, settings)
    page_cutoff = now - int(settings["page_hours"]) * 3600
    page_items = [it for it in archive if it["ts"] >= page_cutoff][: int(settings["max_page_items"])]
    core, core_from = get_osint_core(settings)

    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE.write_text(json.dumps(archive, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    banner = os.environ.get("NEWSFEED_BANNER", "")
    (OUT / "index.html").write_text(
        render_page(page_items, beats, settings, now, feeds, ok, banner), encoding="utf-8")
    (OUT / "osint-core.js").write_text(core, encoding="utf-8")
    (OUT / "status.html").write_text(render_status(results, settings, now, core_from), encoding="utf-8")
    (OUT / "feed.xml").write_text(render_rss(page_items, settings, now), encoding="utf-8")
    (OUT / "feed.json").write_text(json.dumps(page_items, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    write_step_summary(results)

    print(f"{ok}/{len(feeds)} sources responded · {added} new stories · "
          f"{len(page_items)} on page · {len(archive)} in archive · formatter: {core_from}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
