#!/usr/bin/env python3
"""session.py -- read what the API will not hand over, using a real browser.

    python3 tools/vk/session.py login     # opens Brave; log in to VK once
    python3 tools/vk/session.py wiki      # fetch every wiki page the corpus names
    python3 tools/vk/session.py docs      # list + download the Files sections
    python3 tools/vk/session.py status

WHY THIS EXISTS, AND WHY IT IS A LAST RESORT.  Wiki pages and the Files
sections are not reachable through any supported API route, and each route was
tested rather than assumed:

    service key            -> error 28,   method unavailable with service token
    VK ID user key         -> error 1051, method unavailable for this profile
                              type -- and it fires for the operator's OWN docs
                              and OWN group list, so it is the token class and
                              not a permission on those communities
    m.vk.ru unauthenticated-> login wall  (it serves ARTICLES fine, not pages)
    a stored doc url       -> HTTP 418
    Wayback CDX            -> zero snapshots of page-<gid>* or docs-<gid>*

VK ID cannot grant the classic `pages`/`docs`/`groups` scopes at all, and the
flows that could were disabled on 25 June 2024.  So the only remaining reader
is a logged-in browser.

THE SESSION IS THE OPERATOR'S OWN, AND IT STAYS ON THIS MACHINE.  Brave runs
against a DEDICATED profile under ../donotpublish/ -- not the operator's daily
profile, which is never opened, read or modified.  Nothing here exports,
uploads or prints a cookie.  Only public group content is read, at the same
rate a person clicking would.

ponytail: one file, and it reuses mine.py's database rather than inventing a
second store.
"""
import io, json, os, re, sqlite3, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mine                                          # noqa: E402

PROFILE = os.path.join(os.path.dirname(mine.DB), "..", "..", ".vk-brave-profile")
BRAVE = "/opt/brave-origin-bin/brave"
FILES = os.path.join(os.path.dirname(mine.DB), "files")
PACE = 1.2                                           # be a person, not a swarm


def ctx(pw, headless):
    os.makedirs(PROFILE, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        PROFILE, headless=headless,
        executable_path=BRAVE if os.path.exists(BRAVE) else None,
        args=["--no-first-run", "--no-default-browser-check"],
        viewport={"width": 1400, "height": 950})


def logged_in(page):
    """VK's session cookie is `remixsid`; its presence is the only signal."""
    return any(c["name"].startswith("remixsid") for c in page.context.cookies())


def run():
    """Log in and fetch in ONE browser lifetime.

    ⚠️ VK's authenticated cookie `remixsid` is a SESSION cookie: Chromium keeps
    it in memory and never writes it to the profile's Cookies database, so it
    does not survive closing the browser. Logging in, quitting, and relaunching
    headless looks like it should work and silently yields an anonymous
    context -- the login really did succeed, the cookie really is gone. So the
    window stays open from login through the last fetch.
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = ctx(pw, headless=False)
        p = b.pages[0] if b.pages else b.new_page()
        p.goto("https://vk.ru/", timeout=60000)
        if not logged_in(p):
            print("Log in to VK in the window that opened. Waiting up to 5 min…",
                  flush=True)
            for _ in range(300):
                if logged_in(p):
                    break
                time.sleep(1)
            else:
                b.close()
                sys.exit("no VK session appeared")
        print("session live -- do NOT close the window until this finishes\n",
              flush=True)
        c = mine.db()
        _wiki(c, p)
        try:
            _docs(c, p)          # the Files SECTIONS are empty; the files are
        except Exception as e:   # wall attachments, so never let this block them
            print("  (docs listing skipped: %s)" % e, flush=True)
        _files(c, b, p)
        c.commit()
        b.close()


def login():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        c = ctx(pw, headless=False)
        p = c.pages[0] if c.pages else c.new_page()
        p.goto("https://vk.ru/", timeout=60000)
        print("Log in to VK in the window that opened. Waiting up to 5 minutes…")
        for _ in range(300):
            if logged_in(p):
                print("session established; it persists in %s" % PROFILE)
                time.sleep(2)
                c.close()
                return
            time.sleep(1)
        c.close()
        sys.exit("no VK session appeared -- nothing was saved")


def page_ids(c):
    """Every wiki page the corpus mentions, as (owner_id, page_id)."""
    out = set()
    pat = re.compile(r"vk\.(?:com|ru)/page-?(\d+)_(\d+)")
    for (t,) in c.execute("SELECT text FROM item WHERE text LIKE '%/page%'"):
        for m in pat.finditer(t):
            out.add((int(m.group(1)), int(m.group(2))))
    for (u,) in c.execute("SELECT url FROM attach WHERE url LIKE '%/page%'"):
        for m in pat.finditer(u or ""):
            out.add((int(m.group(1)), int(m.group(2))))
    return sorted(out)


NAMES = {v: k for k, v in mine.GROUP_IDS.items()}


def wiki():
    sys.exit("use: session.py run  (the VK session cookie does not survive a "
             "browser restart -- see run()'s docstring)")


def _wiki(c, p):
    from playwright.sync_api import TimeoutError as PWTimeout
    targets = page_ids(c)
    print("%d distinct wiki pages referenced by the corpus" % len(targets))
    if True:
        ok = skipped = failed = 0
        for i, (oid, pid) in enumerate(targets, 1):
            key = "wikipg/%d_%d" % (oid, pid)
            if mine.resume(c, key):
                skipped += 1
                continue
            url = "https://vk.ru/page-%d_%d" % (oid, pid)
            try:
                p.goto(url, timeout=45000, wait_until="domcontentloaded")
                p.wait_for_timeout(700)
                title = (p.title() or "").strip()
                body = p.inner_text("body")
            except PWTimeout:
                failed += 1
                mine.mark(c, key, 1)
                print("  [%3d/%d] %-26s TIMEOUT" % (i, len(targets), key))
                continue
            body = "\n".join(l.strip() for l in body.splitlines() if l.strip())
            grp = NAMES.get(oid, str(oid))
            uid = "wiki:%d_%d" % (oid, pid)
            txt = title + "\n" + body
            c.execute("INSERT OR REPLACE INTO item VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (uid, grp, "wiki", pid, oid, 0, 0, txt, url, ""))
            c.execute("DELETE FROM ft WHERE uid=?", (uid,))
            c.execute("INSERT INTO ft VALUES(?,?,?,?)", (uid, grp, "wiki", txt))
            mine.mark(c, key, 1)
            ok += 1
            print("  [%3d/%d] %-11s %-42s %6d chars"
                  % (i, len(targets), grp, title[:42], len(body)), flush=True)
            time.sleep(PACE)
        c.commit()
    print("\nwiki: %d fetched, %d already had, %d failed" % (ok, skipped, failed))


def docs():
    sys.exit("use: session.py run")


def _docs(c, p):
    os.makedirs(FILES, exist_ok=True)
    if True:
        print("\nFiles sections:", flush=True)
        for grp, gid in mine.GROUP_IDS.items():
            url = "https://vk.ru/docs-%d" % gid
            p.goto(url, timeout=45000, wait_until="domcontentloaded")
            p.wait_for_timeout(1500)
            for _ in range(20):                       # the list is lazy-loaded
                p.mouse.wheel(0, 4000)
                p.wait_for_timeout(600)
            rows = p.eval_on_selector_all(
                "a[href*='/doc']",
                "es => es.map(e => [e.href, (e.innerText||'').trim()])")
            seen = {}
            for href, name in rows:
                m = re.search(r"/doc(-?\d+_\d+)", href)
                if m:
                    seen[m.group(1)] = name
            print("  %-14s %d files listed" % (grp, len(seen)))
            for did, name in seen.items():
                c.execute("INSERT INTO attach VALUES(?,?,?,?,?,?,?)",
                          ("sess:%s:%s" % (grp, did), grp, "doc", name, "", 0,
                           "https://vk.ru/doc%s" % did))
            c.commit()


def _files(c, ctx_, page):
    """Download the documents the corpus points at, through the live session.

    The urls were already harvested from wall attachments by mine.py; what was
    missing is authorisation. Fetched anonymously they answer HTTP 418, and
    docs.get is refused to both a service key (28) and a VK ID user key (1051).
    A logged-in browser context is the only thing that can read them.

    GIFs are skipped: 142 of them, 1.1 GB, and they are reaction images.
    """
    os.makedirs(FILES, exist_ok=True)
    rows = [r for r in c.execute(
        "SELECT DISTINCT url,title,ext,size FROM attach "
        "WHERE type='doc' AND url<>''")
        if (r[2] or "").lower() != "gif"]
    print("\n%d documents to fetch (%.0f MB)"
          % (len(rows), sum(r[3] or 0 for r in rows) / 1e6), flush=True)
    got = skip = bad = 0
    for i, (url, title, ext, size) in enumerate(rows, 1):
        m = re.search(r"/doc(-?\d+_\d+)", url)
        did = m.group(1) if m else str(i)
        safe = re.sub(r"[^\w.\-]", "_", (title or did))[:70].lstrip("-.") or "f"
        dst = os.path.join(FILES, "%s_%s" % (did, safe))
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            skip += 1
            continue
        try:
            body = None
            for attempt in range(3):
                r = ctx_.request.get(url, timeout=180000)
                if r.status != 200:
                    raise RuntimeError("HTTP %d" % r.status)
                body = r.body()
                ctype = (r.headers or {}).get("content-type", "")
                # VK answers a ~289 KB HTML page instead of the file when it
                # declines -- and it serves it under the real filename, so a
                # length check does NOT catch it. 39 files were saved as bogus
                # `.dll`/`.ttf`/`.cfg` before this was noticed. Check the TYPE.
                looks_html = ("text/html" in ctype.lower()
                              or body[:512].lstrip()[:9].lower()
                              in (b"<!doctype", b"<html")
                              or b"<!DOCTYPE html" in body[:512])
                if not looks_html:
                    break
                body = None
                time.sleep(3 * (attempt + 1))     # often just throttling
            if body is None:
                raise RuntimeError("served HTML, not the file (declined x3)")
            with open(dst, "wb") as f:
                f.write(body)
            got += 1
            print("  [%3d/%d] %-52s %8d b" % (i, len(rows), safe[:52], len(body)),
                  flush=True)
        except Exception as e:
            bad += 1
            print("  [%3d/%d] %-52s FAILED %s" % (i, len(rows), safe[:52], e),
                  flush=True)
        time.sleep(PACE / 2)
    print("\nfiles: %d downloaded, %d already had, %d failed -> %s"
          % (got, skip, bad, FILES))


def status():
    c = mine.db()
    n = c.execute("SELECT count(*) FROM item WHERE kind='wiki'").fetchone()[0]
    tot = len(page_ids(c))
    print("wiki pages: %d fetched of %d referenced" % (n, tot))
    print("profile   : %s (%s)" % (PROFILE, "present" if os.path.isdir(PROFILE) else "absent"))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"run": run, "login": login, "wiki": wiki, "docs": docs,
     "status": status}.get(
        cmd, lambda: sys.exit(__doc__))()
