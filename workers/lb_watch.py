"""lb_watch.py — count OUR rows in the top-100 duel board.
Login with slot-0 account, pull get_leaderboards{322}, case-insensitive
name match. Prints OURS_TOP100=n (and TOP1 line). Exit 0 always on a
successful read; exit 2 on game/API failure (watchdog treats as no-decision).
Env: FARM_ACCOUNTS_JSON, OURS_NAMES (comma list, default 'fuck you kekki').
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

try:
    c = Client(HOST, timeout=15)
    c.handshake()
    sess = c.session
    fv = hashlib.sha1((sess + X).encode()).hexdigest().upper()
    pw = hashlib.md5((sess + GUID).encode()).hexdigest()
    c.req = 0
    c._send('LOGIN', login_payload(GUID, pw, SYSID, fv))
    if c._recv().get(4, [None])[0] is not None:
        print('LOGIN FAIL', flush=True)
        raise SystemExit(2)
    c.drain(timeout=2)
    c.req += 1
    send_frame(c.s, envelope(c.req, 'get_leaderboards', fvar(1, 322)))
    o = c.s.gettimeout(); c.s.settimeout(20)
    try:
        _, fb = rd_frame(c.s)
    finally:
        c.s.settimeout(o)
    f = parse_fields(fb)
    if f.get(4, [None])[0] is not None:
        print('LB ERR', flush=True)
        raise SystemExit(2)
    p = f.get(3, [b''])[0] if 3 in f else b''
    rows = parse_fields(parse_fields(p)[2][0])[1]
    ours = 0
    top1 = '?/?'
    for i, r in enumerate(rows):
        m = parse_fields(r)
        nm = m.get(2, [b''])[0]
        nm = nm.decode(errors='replace') if isinstance(nm, bytes) else str(nm)
        if i == 0:
            top1 = '%s/%s' % (nm[:24], m.get(4, ['?'])[0])
        if nm.lower() in WANT:
            ours += 1
    print('OURS_TOP100=%d NROWS=%d TOP1=%s' % (ours, len(rows), top1), flush=True)
    c.close()
except SystemExit as e:
    raise
except Exception as ex:
    print('WATCH FAIL %s' % str(ex)[:120], flush=True)
    raise SystemExit(2)
