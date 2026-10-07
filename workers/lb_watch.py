"""lb_watch.py — count OUR rows in the top-100 duel board + per-slot detail.
Login with slot-0 account, pull get_leaderboards{322}, case-insensitive
name match. Prints OURS_TOP100=n (and TOP1 line). Exit 0 always on a
successful read; exit 2 on game/API failure (watchdog treats as no-decision).
Env: FARM_ACCOUNTS_JSON, OURS_NAMES (comma list, default 'fuck you kekki').
Per-slot detail (DETAIL=1): login every account, resolve pid+wins via
get_player, match to board, print SLOT=i pid=.. wins=.. rank=.. rating=..
and OURS_TOP3 slots. Never prints guid/sysid (slot index only).
"""
import sys, time, hashlib, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sf3 import Client, login_payload, envelope, send_frame, rd_frame, parse_fields, fvar, fbytes, D_SUM, CONFIG_VER
import sf3 as S

X = 'D61109D768EDAA3AD2EFA9EF357BD1AE33D5F0AB'
ACCTS = json.loads(os.environ['FARM_ACCOUNTS_JSON'])
A = ACCTS[0]
GUID, SYSID, HOST = A['guid'], A['sysid'], A.get('host', '52.66.28.201')
WANT = [n.strip().lower() for n in os.environ.get('OURS_NAMES', 'fuck you kekki').split(',') if n.strip()]

def login(acct):
    c = Client(acct.get('host', '52.66.28.201'), timeout=15)
    c.handshake()
    sess = c.session
    fv = hashlib.sha1((sess + X).encode()).hexdigest().upper()
    pw = hashlib.md5((sess + acct['guid']).encode()).hexdigest()
    c.req = 0
    c._send('LOGIN', login_payload(acct['guid'], pw, acct['sysid'], fv))
    if c._recv().get(4, [None])[0] is not None:
        c.close()
        return None, None
    c.drain(timeout=2)
    return c, sess

def raw(c, cmd, pay=None, timeout=20):
    c.req += 1
    send_frame(c.s, envelope(c.req, cmd, pay))
    o = c.s.gettimeout(); c.s.settimeout(timeout)
    try:
        _, fb = rd_frame(c.s)
    finally:
        c.s.settimeout(o)
    f = parse_fields(fb)
    return f.get(4, [None])[0], (f.get(3, [b''])[0] if 3 in f else b'')

try:
    c, sess = login(A)
    if c is None:
        print('LOGIN FAIL', flush=True)
        raise SystemExit(2)
    e, p = raw(c, 'get_leaderboards', fvar(1, 322))
    if e is not None:
        print('LB ERR', flush=True)
        c.close()
        raise SystemExit(2)
    rows = parse_fields(parse_fields(p)[2][0])[1]
    bypid = {}
    ours = 0
    top1 = '?/?'
    for i, r in enumerate(rows):
        m = parse_fields(r)
        nm = m.get(2, [b''])[0]
        nm = nm.decode(errors='replace') if isinstance(nm, bytes) else str(nm)
        rt = m.get(4, [0])[0]
        if i == 0:
            top1 = '%s/%s' % (nm[:24], rt)
        if nm.lower() in WANT:
            ours += 1
        if isinstance(m.get(1, [None])[0], int):
            bypid[m[1][0]] = (i + 1, nm[:24], rt)
    print('OURS_TOP100=%d NROWS=%d TOP1=%s' % (ours, len(rows), top1), flush=True)
    c.close()
    hits = []
    for i, acct in enumerate(ACCTS):
        try:
            cc, ss = login(acct)
            if cc is None:
                print('SLOT=%d LOGIN_FAIL' % i, flush=True)
                continue
            try:
                s = hashlib.sha1((ss + D_SUM).encode()).hexdigest().upper()
                h = S.fstr(1, 'sum') + S.fstr(2, s)
                pid, wins = None, 0
                for _ in range(3):
                    ee, pp = raw(cc, 'get_player', S.fstr(1, CONFIG_VER) + fbytes(2, b'') + fbytes(3, h) + S.fstr(4, 'google Pixel 4') + S.fstr(5, S.APP_VER))
                    top = parse_fields(pp) if pp else {}
                    if ee is None and 1 in top and isinstance(top[1][0], bytes):
                        inner = parse_fields(top[1][0])
                        sp = parse_fields(inner[1][0])
                        pid = sp.get(1, [None])[0]
                        wins = inner.get(16, [0])[0]
                        break
                if pid is None:
                    print('SLOT=%d NO_PLAYER' % i, flush=True)
                    continue
                if pid in bypid:
                    rk, _, rt = bypid[pid]
                    hits.append((rk, rt, wins, i, pid))
                    print('SLOT=%d pid=%d wins=%d rank=%d rating=%d' % (i, pid, wins, rk, rt), flush=True)
                else:
                    print('SLOT=%d pid=%d wins=%d OFFBOARD' % (i, pid, wins), flush=True)
            finally:
                cc.close()
        except Exception as ex:
            print('SLOT=%d ERR %s' % (i, str(ex)[:80]), flush=True)
    hits.sort()
    print('OURS_ONBOARD=%d' % len(hits), flush=True)
    for h in hits[:10]:
        print('TOP rank=%d rating=%d wins=%d slot=%d pid=%d' % (h[0], h[1], h[2], h[3], h[4]), flush=True)
    print('OURS_TOP3=' + ','.join(str(h[3]) for h in hits[:3]), flush=True)
except SystemExit as e:
    raise
except Exception as ex:
    print('WATCH FAIL %s' % str(ex)[:120], flush=True)
    raise SystemExit(2)
