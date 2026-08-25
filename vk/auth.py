#!/usr/bin/env python3
"""auth.py -- get a VK *user* access key through VK ID, in a browser.

    python3 tools/vk/auth.py login --app-id 12345678
    python3 tools/vk/auth.py status
    python3 tools/vk/auth.py refresh

WHY THIS EXISTS.  A service key reads walls, comments and topic boards fine,
but `groups.search` refuses it -- verified against two independent service keys,
both answering `error 15, Access denied`.  Enumerating every Sacred community
therefore needs a user key, and a user key needs a human in a browser.

WHAT VK CHANGED.  The old ways in are gone: Authorization Code Flow and
Implicit Flow for user keys were both disabled 25 June 2024, and Client
Credentials for service keys on 17 October 2022.  What is left is VK ID's
OAuth 2.1 with PKCE, which is what this implements.

NO CLIENT SECRET IS USED OR WANTED.  VK ID's code exchange is a public-client
PKCE flow -- the docs' own curl example passes no client_secret -- so the
app's "protected key" (защищённый ключ) is not needed here and must not be
pasted in.  The only app value required is the numeric app id, which is not a
secret.

⚠️ THE TOKEN LIVES ONE HOUR.  `refresh` swaps the refresh_token for a new pair
and is the only reason this stores anything at all.

Tokens are written to ../donotpublish/.vk-user-token, mode 0600 -- inside the
unpublished workspace, exactly like the service key.  This repository is
published; never write a credential inside it.

ponytail: stdlib only, one file, no local web framework -- http.server handles
exactly one request and stops.
"""
import base64, hashlib, http.server, json, os, secrets, ssl, subprocess, sys
import time, urllib.error, urllib.parse, urllib.request, webbrowser

AUTH = "https://id.vk.ru/authorize"
TOKEN = "https://id.vk.ru/oauth2/auth"
HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "..", "..", "donotpublish", ".vk-user-token")
REDIRECT = "https://localhost:8910/callback"
# VK ID refuses a plain-http redirect outright -- the app form answers
# "Обязателен протокол https" -- so the local catcher has to speak TLS.
CERT = os.path.join(os.path.dirname(STORE), ".vk-localhost-cert.pem")
PENDING = os.path.join(os.path.dirname(STORE), ".vk-auth-pending")
# vkid.personal_info is the documented default when scope is omitted; groups is
# what groups.search wants.  If VK rejects a scope it says so in the redirect.
SCOPE = "vkid.personal_info groups"


def b64(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def post(**form):
    body = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(
        TOKEN, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=45))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8", "replace"))


def save(d):
    d["obtained"] = int(time.time())
    d["expires_at"] = d["obtained"] + int(d.get("expires_in") or 3600)
    old = os.umask(0o077)
    try:
        with open(STORE, "w") as f:
            json.dump(d, f, indent=1)
    finally:
        os.umask(old)
    os.chmod(STORE, 0o600)
    return d


def load():
    try:
        with open(STORE) as f:
            return json.load(f)
    except OSError:
        return None


def catch(redirect):
    """Serve exactly one request on the redirect port and return its query.

    VK requires the redirect page to carry no scripts and no embedded content
    -- an image or a stylesheet would leak the code through Referer -- so the
    reply here is deliberately bare text/plain.
    """
    u = urllib.parse.urlparse(redirect)
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            got.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            ok = "code" in got
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(("authorised, you can close this tab"
                              if ok else "no code in callback").encode())

        def log_message(self, *a):
            pass

    try:
        srv = http.server.HTTPServer((u.hostname, u.port or (443 if u.scheme == "https" else 80)), H)
    except OSError as e:
        sys.exit("cannot listen on %s: %s" % (redirect, e))
    if u.scheme == "https":
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(selfsigned())
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    srv.timeout = 300
    srv.handle_request()
    srv.server_close()
    return {k: v[0] for k, v in got.items()}


def selfsigned():
    """A throwaway localhost certificate, made once and reused.

    The browser will warn that it is not trusted -- that is expected and has to
    be accepted once. Nothing sensitive rides on this TLS: it exists only
    because VK will not register an http redirect, and the connection never
    leaves the machine.
    """
    if not os.path.exists(CERT):
        old = os.umask(0o077)
        try:
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", CERT, "-out", CERT, "-days", "365",
                 "-subj", "/CN=localhost",
                 "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
                check=True, capture_output=True)
        finally:
            os.umask(old)
        os.chmod(CERT, 0o600)
        print("made a self-signed localhost cert at %s" % CERT)
    return CERT


def login(app_id, redirect, scope):
    verifier = b64(secrets.token_bytes(48))
    challenge = b64(hashlib.sha256(verifier.encode("ascii")).digest())
    state = b64(secrets.token_bytes(32))            # >=32 chars of [A-Za-z0-9_-]
    url = AUTH + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": app_id, "scope": scope,
        "redirect_uri": redirect, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})

    print("\nRedirect URI must be registered in the VK ID app, EXACTLY:\n  %s\n"
          % redirect)
    print("Open this and authorise:\n\n%s\n" % url)
    local = urllib.parse.urlparse(redirect).hostname in ("localhost", "127.0.0.1")
    if local:
        try:
            webbrowser.open(url)
        except Exception:
            pass
        if redirect.startswith("https://localhost"):
            print("⚠️  the browser WILL warn about the self-signed certificate.\n"
                  "    accept it once -- the connection never leaves this machine.")
        print("waiting for the callback on %s ... (5 min)" % redirect)
        q = catch(redirect)
    else:
        # A remote redirect cannot be caught here, and the operator pastes the
        # url back out of band -- possibly into a different process entirely --
        # so the PKCE verifier and state have to outlive this run.
        old = os.umask(0o077)
        try:
            with open(PENDING, "w") as f:
                json.dump({"verifier": verifier, "state": state,
                           "client_id": app_id, "redirect_uri": redirect}, f)
        finally:
            os.umask(old)
        os.chmod(PENDING, 0o600)
        try:
            webbrowser.open(url)          # paste mode still wants the browser
        except Exception:
            pass
        print("Authorise, then hand the FULL url you land on to:\n"
              "    python3 tools/vk/auth.py finish '<pasted-url>'")
        return

    if "code" not in q:
        sys.exit("no code returned: %s" % q)
    if q.get("state") != state:
        sys.exit("state mismatch -- treat this response as forged and retry")

    r = post(grant_type="authorization_code", code=q["code"],
             code_verifier=verifier, client_id=app_id,
             device_id=q.get("device_id", ""), redirect_uri=redirect,
             state=state)
    if "access_token" not in r:
        sys.exit("exchange failed: %s" % json.dumps(r, ensure_ascii=False))
    r["client_id"], r["device_id"] = app_id, q.get("device_id", "")
    r["redirect_uri"] = redirect
    save(r)
    print("\nuser token stored in %s (expires in %ss)" % (STORE, r.get("expires_in")))
    print("scope granted:", r.get("scope"))


def finish(pasted):
    """Complete a paste-mode login from the url the browser landed on."""
    try:
        with open(PENDING) as f:
            pend = json.load(f)
    except OSError:
        sys.exit("no pending login -- run auth.py login --app-id N --redirect URL")
    q = {k: v[0] for k, v in
         urllib.parse.parse_qs(urllib.parse.urlparse(pasted.strip()).query).items()}
    if "code" not in q:
        sys.exit("no ?code= in that url. Paste the whole address bar, including "
                 "everything after the '?'. Got keys: %s" % sorted(q))
    if q.get("state") != pend["state"]:
        sys.exit("state mismatch -- treat this response as forged and start over")
    r = post(grant_type="authorization_code", code=q["code"],
             code_verifier=pend["verifier"], client_id=pend["client_id"],
             device_id=q.get("device_id", ""),
             redirect_uri=pend["redirect_uri"], state=pend["state"])
    if "access_token" not in r:
        sys.exit("exchange failed: %s" % json.dumps(r, ensure_ascii=False))
    r["client_id"] = pend["client_id"]
    r["device_id"] = q.get("device_id", "")
    r["redirect_uri"] = pend["redirect_uri"]
    save(r)
    os.remove(PENDING)
    print("user token stored (expires in %ss)" % r.get("expires_in"))
    print("scope granted:", r.get("scope"))


def refresh():
    d = load() or sys.exit("no stored token -- run: auth.py login --app-id N")
    r = post(grant_type="refresh_token", refresh_token=d["refresh_token"],
             client_id=d["client_id"], device_id=d.get("device_id", ""),
             state=b64(secrets.token_bytes(32)))
    if "access_token" not in r:
        sys.exit("refresh failed: %s" % json.dumps(r, ensure_ascii=False))
    r["client_id"] = d["client_id"]
    r["device_id"] = d.get("device_id", "")
    r["redirect_uri"] = d.get("redirect_uri", REDIRECT)
    save(r)
    print("refreshed, expires in %ss" % r.get("expires_in"))


def token():
    """The live user access key, refreshed if it has expired. None if absent."""
    d = load()
    if not d:
        return None
    if time.time() > d["expires_at"] - 60:
        refresh()
        d = load()
    return d["access_token"]


def status():
    d = load()
    if not d:
        print("no user token stored"); return
    left = int(d["expires_at"] - time.time())
    print("user_id   %s" % d.get("user_id"))
    print("scope     %s" % d.get("scope"))
    print("expires   %s" % ("in %d s" % left if left > 0 else "EXPIRED (refresh)"))
    print("stored    %s" % STORE)


def selftest():
    """RFC 7636 Appendix B vector -- a wrong PKCE transform fails silently at
    the exchange, hours after the mistake, so pin it here instead."""
    v = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    got = b64(hashlib.sha256(v.encode("ascii")).digest())
    assert got == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM", got
    st = b64(secrets.token_bytes(32))
    assert len(st) >= 32 and all(
        ch.isalnum() or ch in "_-" for ch in st), st      # VK's state rule
    print("selftest ok (PKCE vector + state charset)")


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else "status"
    def opt(name, dflt):
        return a[a.index(name) + 1] if name in a else dflt
    if cmd == "--selftest":
        selftest(); sys.exit()
    if cmd == "login":
        app = opt("--app-id", None) or sys.exit("need --app-id N (the numeric "
                                               "app id; NOT the protected key)")
        login(app, opt("--redirect", REDIRECT), opt("--scope", SCOPE))
    elif cmd == "finish":
        finish(a[1] if len(a) > 1 else sys.exit("finish needs the pasted url"))
    elif cmd == "refresh":
        refresh()
    elif cmd == "status":
        status()
    else:
        sys.exit(__doc__)
