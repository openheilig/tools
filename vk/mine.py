#!/usr/bin/env python3
"""mine.py -- pull public VK community content into a local SQLite corpus.

    python3 tools/vk/mine.py overlookers sacredwiki sacred.srrp ...
    python3 tools/vk/mine.py --all              # the five Sacred groups
    python3 tools/vk/mine.py --search "floor.pak"

Reads wall posts, their comments, board topics and topic comments, and records
every attachment (doc/link/photo/video) so files and off-site links are findable
later.  Resumable: every page is checkpointed, so a stall costs one page.

THE TOKEN IS NEVER STORED HERE.  It comes from $VK_TOKEN, or from a file named
by $VK_TOKEN_FILE, or from ../donotpublish/.vk-token relative to this repo --
that path is inside the unpublished workspace by design.  Do not add a default
that points anywhere in this repository.

Service access key is enough: it reads wall.get, board.getTopics and
board.getComments for open communities (verified 2026-08-24).  Nothing here
writes to VK and nothing needs a user login.

ponytail: stdlib only -- urllib and sqlite3's own FTS5.  No requests, no ORM.
"""
import html, json, os, re, sqlite3, sys, time, urllib.error, urllib.parse, urllib.request

GROUPS = ["overlookers", "sacred_nl", "sacredtribute", "sacredwiki", "sacred.srrp"]
API, VER, PAGE = "https://api.vk.ru/method/", "5.199", 100
SLEEP = 0.34                      # service tokens are capped at 3 requests/second
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "..", "donotpublish", "analysis", "vk", "vk.sqlite")


def token():
    if os.environ.get("VK_TOKEN"):
        return os.environ["VK_TOKEN"].strip()
    path = os.environ.get("VK_TOKEN_FILE") or os.path.join(
        HERE, "..", "..", "donotpublish", ".vk-token")
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        sys.exit("no token: set $VK_TOKEN, or $VK_TOKEN_FILE, or create %s" % path)


TOK = None


def api(method, **params):
    """One call, with the two retries that actually happen: rate limit and 5xx."""
    params.update(access_token=TOK, v=VER)
    url = API + method + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            r = json.load(urllib.request.urlopen(url, timeout=60))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(2 ** attempt)
            continue
        err = r.get("error")
        if not err:
            return r["response"]
        if err["error_code"] in (6, 9, 10):          # too many / flood / internal
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError("%s: %s" % (method, err["error_msg"]))
    raise RuntimeError("%s: gave up after 5 attempts" % method)


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS item(
      uid TEXT PRIMARY KEY, grp TEXT, kind TEXT, id INTEGER, parent INTEGER,
      date INTEGER, author INTEGER, text TEXT, url TEXT, raw TEXT);
    CREATE TABLE IF NOT EXISTS attach(
      uid TEXT, grp TEXT, type TEXT, title TEXT, ext TEXT, size INTEGER, url TEXT);
    CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, offset INTEGER);
    CREATE VIRTUAL TABLE IF NOT EXISTS ft USING fts5(uid UNINDEXED, grp, kind, text);
    CREATE INDEX IF NOT EXISTS attach_type ON attach(type);
    """)
    return c


def resume(c, key):
    row = c.execute("SELECT offset FROM state WHERE key=?", (key,)).fetchone()
    return row[0] if row else 0


def mark(c, key, off):
    c.execute("INSERT OR REPLACE INTO state VALUES(?,?)", (key, off))
    c.commit()


def save(c, grp, kind, oid, it, parent=0):
    uid = "%s:%s:%s" % (grp, kind, it["id"])
    text = it.get("text", "") or ""
    url = "https://vk.ru/wall%d_%d" % (oid, it["id"]) if kind == "post" else ""
    c.execute("INSERT OR REPLACE INTO item VALUES(?,?,?,?,?,?,?,?,?,?)",
              (uid, grp, kind, it["id"], parent, it.get("date", 0),
               it.get("from_id", it.get("owner_id", 0)), text, url,
               json.dumps(it, ensure_ascii=False)))
    c.execute("DELETE FROM ft WHERE uid=?", (uid,))
    c.execute("INSERT INTO ft VALUES(?,?,?,?)", (uid, grp, kind, text))
    stack = list(it.get("attachments") or [])
    for rp in it.get("copy_history") or []:          # reposts carry their own
        stack += rp.get("attachments") or []
        if rp.get("text"):
            c.execute("INSERT INTO ft VALUES(?,?,?,?)", (uid, grp, "repost", rp["text"]))
    for a in stack:
        t = a["type"]
        b = a.get(t) or {}
        c.execute("INSERT INTO attach VALUES(?,?,?,?,?,?,?)",
                  (uid, grp, t,
                   b.get("title") or b.get("caption") or b.get("text") or "",
                   b.get("ext", ""), b.get("size", 0),
                   b.get("url") or b.get("link") or ""))


def pages(c, key, total, fetch, handle):
    """Walk an offset-paginated endpoint from wherever it stopped last time."""
    off = resume(c, key)
    while off < total:
        for it in fetch(off):
            handle(it)
        off += PAGE
        mark(c, key, off)
        print("    %-38s %5d/%d" % (key, min(off, total), total), flush=True)
        time.sleep(SLEEP)


def mine(c, name):
    g = api("groups.getById", group_ids=name)["groups"][0]
    gid, oid, grp = g["id"], -g["id"], g["screen_name"]
    print("== %s (%d) %s" % (grp, gid, g["name"]), flush=True)

    n = api("wall.get", owner_id=oid, count=1)["count"]
    pages(c, "%s/wall" % grp, n,
          lambda o: api("wall.get", owner_id=oid, count=PAGE, offset=o)["items"],
          lambda it: save(c, grp, "post", oid, it))
    c.commit()

    for p in c.execute("SELECT id FROM item WHERE grp=? AND kind='post'", (grp,)).fetchall():
        pid = p[0]
        key = "%s/cmts2/%d" % (grp, pid)
        if resume(c, key):
            continue
        # Comments paginate exactly like the wall does.  An earlier version
        # fetched ONE page per post and silently truncated every discussion
        # past 100 -- the busiest threads, which are the ones worth having.
        off, total = 0, 1
        while off < total:
            try:
                r = api("wall.getComments", owner_id=oid, post_id=pid,
                        count=PAGE, offset=off, thread_items_count=10)
            except RuntimeError:
                break                           # deleted, or comments closed
            total = r.get("count", 0)
            for it in r.get("items", []):
                save(c, grp, "comment", oid, it, parent=pid)
                th = it.get("thread") or {}
                for t in th.get("items", []):
                    save(c, grp, "comment", oid, t, parent=pid)
                # thread_items_count caps at 10; deeper replies need their own
                # call, keyed on the parent comment.
                if th.get("count", 0) > len(th.get("items", [])):
                    toff = 0
                    while toff < th["count"]:
                        try:
                            tr = api("wall.getComments", owner_id=oid,
                                     post_id=pid, comment_id=it["id"],
                                     count=PAGE, offset=toff)
                        except RuntimeError:
                            break
                        for t in tr.get("items", []):
                            save(c, grp, "comment", oid, t, parent=pid)
                        toff += PAGE
                        time.sleep(SLEEP)
            off += PAGE
            time.sleep(SLEEP)
        mark(c, key, 1)
    c.commit()

    tr = api("board.getTopics", group_id=gid, count=PAGE)
    for t in tr.get("items", []):
        save(c, grp, "topic", oid, {"id": t["id"], "text": t["title"],
                                    "date": t["created"], "from_id": t["created_by"]})
        pages(c, "%s/topic/%d" % (grp, t["id"]), t["comments"],
              lambda o, tid=t["id"]: api("board.getComments", group_id=gid,
                                         topic_id=tid, count=PAGE, offset=o)["items"],
              lambda it, tid=t["id"]: save(c, grp, "tcomment", oid, it, parent=tid))
    c.commit()


URL_RE = re.compile(r"https?://[^\s\)\]\"'<>,]+", re.I)
# VK wraps outbound links; the real target is the ?to= parameter.
AWAY_RE = re.compile(r"vk\.(?:com|ru)/away\.php\?to=([^&\s]+)", re.I)
SKIP = ("vk.com", "vk.ru", "vk.me", "userapi.com", "vkuserphoto.ru",
        "vkuservideo.ru", "vk.cc", "userapi.ru")


def links(c, dump=False):
    """Every off-site URL the corpus mentions, by host.

    Links live in three places and a miner that reads only one under-reports:
    the `link` attachment, the `doc` attachment's own download url, and bare
    urls typed into post and comment text.  All three are merged here.
    """
    found = {}                                    # url -> (host, kind, first title)
    def add(u, kind, title=""):
        u = urllib.parse.unquote(u).rstrip(".,);'\"")
        if not u.lower().startswith("http"):
            return
        host = (urllib.parse.urlparse(u).netloc or "").lower().lstrip("www.")
        if not host or any(host == s or host.endswith("." + s) for s in SKIP):
            return
        found.setdefault(u, (host, kind, title))

    for typ, title, url in c.execute(
            "SELECT type,title,url FROM attach WHERE url<>''"):
        add(url, typ, title or "")
    for (text,) in c.execute("SELECT text FROM item WHERE text<>''"):
        for m in AWAY_RE.finditer(text):
            add(urllib.parse.unquote(m.group(1)), "away")
        for u in URL_RE.findall(text):
            add(AWAY_RE.sub("", u) if "away.php" in u else u, "text")

    hosts = {}
    for u, (h, k, t) in found.items():
        hosts.setdefault(h, []).append((u, k, t))
    if dump:
        for u in sorted(found):
            print(u)
        return
    print("%-42s %6s  %s" % ("host", "links", "sample"))
    for h, v in sorted(hosts.items(), key=lambda x: -len(x[1])):
        print("%-42s %6d  %s" % (h[:42], len(v), v[0][0][:70]))
    print("\n%d distinct off-site urls across %d hosts" % (len(found), len(hosts)))


ART_RE = re.compile(r"https?://(?:m\.)?vk\.(?:com|ru)/(@[\w.\-]+)", re.I)
# A plain browser UA is enough.  vk.ru itself answers "your browser is
# outdated" and the desktop SPA never renders server-side, but the MOBILE host
# returns the article as real HTML.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def untag(html_text):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", t, flags=re.I)
    return "\n".join(
        ln.strip() for ln in html.unescape(re.sub(r"<[^>]+>", " ", t)).splitlines()
        if ln.strip())


def articles(c):
    """VK long-form articles.

    There is no API for these -- `articles.get` answers "Unknown method
    passed" and no wall attachment carries type `article` -- so the only
    handle is the /@slug urls the posts themselves link, which is why this
    runs after the walls are mined rather than beside them.
    """
    urls = set()
    for (u,) in c.execute("SELECT url FROM attach WHERE url LIKE '%/@%'"):
        m = ART_RE.search(u or "")
        if m:
            urls.add(m.group(1))
    for (t,) in c.execute("SELECT text FROM item WHERE text LIKE '%/@%'"):
        for m in ART_RE.finditer(t):
            urls.add(m.group(1))
    print("%d distinct articles referenced" % len(urls), flush=True)
    for i, slug in enumerate(sorted(urls), 1):
        key = "article/%s" % slug
        if resume(c, key):
            continue
        url = "https://m.vk.ru/" + slug
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Language": "ru,en"})
            raw = urllib.request.urlopen(req, timeout=45).read()
        except Exception as e:
            print("    %-58s FAILED %s" % (slug[:58], e), flush=True)
            mark(c, key, 1)
            continue
        page = raw.decode("utf-8", "replace")
        ttl = re.search(r"<title>(.*?)</title>", page, re.S)
        ttl = html.unescape(ttl.group(1)).strip() if ttl else slug
        body = untag(page)
        grp = slug[1:].split("-")[0]
        uid = "article:%s" % slug
        c.execute("INSERT OR REPLACE INTO item VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (uid, grp, "article", 0, 0, 0, 0, ttl + "\n" + body, url, ""))
        c.execute("DELETE FROM ft WHERE uid=?", (uid,))
        c.execute("INSERT INTO ft VALUES(?,?,?,?)", (uid, grp, "article",
                                                     ttl + "\n" + body))
        mark(c, key, 1)
        print("    [%3d/%d] %-52s %6d chars" % (i, len(urls), slug[:52], len(body)),
              flush=True)
        time.sleep(SLEEP)
    c.commit()


def search(c, q):
    rows = c.execute("""SELECT f.grp, f.kind, i.date, i.url, snippet(ft,3,'>>','<<','…',18)
                        FROM ft f JOIN item i ON i.uid=f.uid
                        WHERE ft MATCH ? ORDER BY rank LIMIT 60""", (q,)).fetchall()
    for g, k, d, u, s in rows:
        print("%-13s %-9s %s %s\n    %s" % (
            g, k, time.strftime("%Y-%m-%d", time.gmtime(d)) if d else "?", u,
            " ".join(s.split())))
    print("\n%d hits" % len(rows))


def selftest():
    """The smallest thing that fails if save() stops recording attachments."""
    global DB
    DB = ":memory:"
    c = sqlite3.connect(DB)
    c.executescript(open(__file__).read().split('c.executescript("""')[1].split('""")')[0])
    save(c, "g", "post", -1, {"id": 7, "text": "floor.pak сектор", "date": 1,
                              "attachments": [{"type": "doc", "doc": {
                                  "title": "x.rar", "ext": "rar", "size": 9,
                                  "url": "http://e/x"}}]})
    assert c.execute("SELECT count(*) FROM attach WHERE ext='rar'").fetchone()[0] == 1
    assert c.execute("SELECT count(*) FROM ft WHERE ft MATCH 'сектор'").fetchone()[0] == 1
    print("selftest ok")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--selftest":
        selftest(); sys.exit()
    TOK = token()
    c = db()
    if a and a[0] == "--search":
        search(c, " ".join(a[1:])); sys.exit()
    if a and a[0] == "--links":
        links(c, dump="--dump" in a); sys.exit()
    if a and a[0] == "--articles":
        articles(c); sys.exit()
    for name in (GROUPS if (not a or a[0] == "--all") else a):
        mine(c, name)
    print("\ncorpus:", DB)
    for k, n in c.execute("SELECT kind,count(*) FROM item GROUP BY kind"):
        print("  %-9s %6d" % (k, n))
