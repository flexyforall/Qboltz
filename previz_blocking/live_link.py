"""live_link -- Claude -> your Blender, no Claude on this computer.

Run ONCE per Blender session: Scripting tab -> Open this file -> Run Script.
Every few seconds it checks the branch below on GitHub. When Claude pushes a
new commit, it downloads previz_blocking/live.py at exactly that commit and runs
it here, so the scene rebuilds in your viewport by itself.

Run it again to STOP. The header of every 3D view shows LIVE status.
It only ever runs code from this one repo + branch.
"""
import bpy, re, ssl, threading, time, traceback, urllib.request

REPO   = "flexyforall/Qboltz"
BRANCH = "claude/sweet-planck-eka5fw"
PATH   = "previz_blocking/live.py"
POLL_S = 3.0

NS = bpy.app.driver_namespace

def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "blender-live-link",
                                               "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=10, context=_ctx()) as r:
        return r.read()

def head_sha():
    # git's own ref advertisement: not cached and not API-rate-limited
    refs = _get(f"https://github.com/{REPO}.git/info/refs?service=git-upload-pack")
    m = re.search(rb"([0-9a-f]{40}) refs/heads/" + re.escape(BRANCH.encode()) + rb"[\0\n]", refs)
    return m.group(1).decode() if m else None

def fetch(sha):
    # a commit-pinned raw URL never serves a stale cached copy
    return _get(f"https://raw.githubusercontent.com/{REPO}/{sha}/{PATH}").decode()

def _status(text):
    NS["LIVE_STATUS"] = text
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D': a.tag_redraw()

def _header(self, context):
    s = NS.get("LIVE_STATUS")
    if s: self.layout.label(text=s, icon='LINKED')

def _apply(sha, src):
    w = bpy.context.window_manager.windows[0]
    try:
        with bpy.context.temp_override(window=w, screen=w.screen):
            exec(compile(src, "live.py@" + sha[:7], "exec"), {"__name__": "__live__"})
        _status("LIVE  %s  updated %s" % (sha[:7], time.strftime("%H:%M:%S")))
        print("[live_link] applied", sha[:7])
    except Exception:
        traceback.print_exc()
        _status("LIVE  %s  ERROR -- see console" % sha[:7])

def _worker(stop):
    while not stop.is_set():
        try:
            sha = head_sha()
            if sha and sha != NS.get("LIVE_SHA"):
                src = fetch(sha)
                NS["LIVE_SHA"] = sha
                NS["LIVE_PENDING"] = (sha, src)
        except Exception as e:
            NS["LIVE_NETERR"] = str(e)
        stop.wait(POLL_S)

def _tick():
    if "LIVE_STOP_EVT" not in NS: return None
    p = NS.pop("LIVE_PENDING", None)
    if p: _apply(*p)
    err = NS.pop("LIVE_NETERR", None)
    if err and not NS.get("LIVE_SHA"):
        _status("LIVE  no connection: %s" % err[:60])
    return 0.5

def stop():
    evt = NS.pop("LIVE_STOP_EVT", None)
    if evt: evt.set()
    try: bpy.types.VIEW3D_HT_header.remove(_header_ref())
    except Exception: pass
    for k in ("LIVE_STATUS", "LIVE_SHA", "LIVE_PENDING", "LIVE_HEADER"): NS.pop(k, None)
    _status("")
    print("[live_link] stopped")

def _header_ref(): return NS.get("LIVE_HEADER")

if "LIVE_STOP_EVT" in NS:
    NS["LIVE_STOP"]()                              # second run = switch off
else:
    evt = threading.Event()
    NS["LIVE_STOP_EVT"], NS["LIVE_STOP"], NS["LIVE_HEADER"] = evt, stop, _header
    bpy.types.VIEW3D_HT_header.append(_header)
    _status("LIVE  connecting...")
    threading.Thread(target=_worker, args=(evt,), daemon=True).start()
    bpy.app.timers.register(_tick, first_interval=0.5)
    print("[live_link] watching %s @ %s" % (REPO, BRANCH))
