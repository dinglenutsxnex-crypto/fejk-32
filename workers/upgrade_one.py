"""upgrade_one.py — advance ONE existing mint-CSV account 36 -> 270 + faction select.
Proven chain logic (same submit/qmap/retry as local chain.py). Stdlib only.
Usage: upgrade_one.py --csv mint/mint-eu.csv --index N [--stop 270]
Exits 0 on faction-selected + brawler-clean, 1 otherwise.
"""
import sys, time, hashlib, json, os, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sf3 import Client, login_payload, envelope, send_frame, rd_frame, parse_fields, varint, fvar, fstr, fbytes, ping_payload, D_SUM, CONFIG_VER
import sf3 as S

X = 'D61109D768EDAA3AD2EFA9EF357BD1AE33D5F0AB'
MASK = (1 << 64) - 1
GEN = {
    "10": {"f4": 1, "f5": 1, "f7": 1, "f8": [[1, 6], [3, 3], [4, 1], [5, 3], [6, None], [7, None]], "f10": "", "f13": "103b1a01002201312a02840132049060663f3a040000000042040852073e4a0112520106", "f14": None},
    "20": {"f4": 1, "f5": 2, "f7": 2, "f8": [[1, 8], [3, 3], [5, 3], [6, None], [7, None], [4, 1]], "f10": "", "f13": "10451a020000220222152a023622320866fc6b3f18476b3f3a080000000000000000420861f85e3ed0f73b3e4a02090752020703", "f14": None},
    "30": {"f4": 1, "f5": 2, "f7": 2, "f8": [[1, 3], [2, 3], [5, 3], [6, None], [7, None], [4, 1]], "f10": "", "f13": "103f1a0200002202171a2a0236313208438b7c3f2cb2593f3a08000000000000000042080cde7e3e295c4f3e4a02070852020202", "f14": None},
    "35": {"f4": 1, "f5": 2, "f7": 2, "f8": [[1, 6], [3, 3], [4, 2], [5, 3], [6, None], [7, None], [2, 1]], "f10": "", "f13": "0830104e1a020f21220215272a0247713208cfe97c3fb9c6d73e3a08000000000000000042086dc6103e44413d3e4a020d095202010c", "f14": 48},
    "36": {"f4": 1, "f5": 2, "f7": 2, "f8": [[1, 6], [4, 1], [6, None], [7, None], [2, 3]], "f10": "", "f13": "0833104d1a02191a22021e1f2a025c5732083b50533f8e71e73e3a08000000000000000042085c12143e14ae473e4a02120b52020205", "f14": 51},
    "40": {"f4": 1, "f5": 3, "f7": 3, "f8": [[1, 14], [4, 3], [5, 6], [6, None], [7, None], [2, 6], [3, 4]], "f10": "", "f13": "08970110c0011a032c2f3c22033034422a06bd01c0019102320c29eb433fc5b8243ffc3afd3e3a0c000000000000000000000000420c58f09c3df0f6bd3d54f09c3d4a031b181c520306070c", "f14": 151},
    "45": {"f4": 1, "f5": 2, "f7": 2, "f8": [[1, 8], [2, 3], [3, 3], [4, 2], [5, 4], [6, None], [7, None]], "f10": "0a04080310050a04081c10030a04081b10030a04080210020a04081a1001", "f13": "083610551a021e18220226202a026d653208432b183f52387d3f3a080000000000000000420860d10a3e68ee723e4a02101352020501", "f14": 54},
}
GENUINE = {10: "10", 20: "20", 30: "30", 35: "35", 36: "36", 40: "40"}
CHAIN = [40, 45, 46, 48, 50, 60, 70, 80, 90, 95, 100,
         110, 120, 130, 140, 150, 160, 170, 180, 190, 200, 210,
         220, 230, 240, 250, 260, 270]
ROUNDS = {40: 3, 45: 2, 46: 2, 48: 2, 50: 1, 60: 3, 70: 2, 80: 2, 90: 2,
          95: 2, 100: 3, 150: 3, 210: 3, 270: 3}
CAP = {1: lambda r: 50 * r, 2: lambda r: 5 * r, 3: lambda r: 50 * r,
       4: lambda r: 1 * r, 5: lambda r: 50, 6: lambda r: 1 * r, 7: lambda r: 1 * r}
WI = bytes.fromhex('0a0508d10c10040a0508d20c10040a0508d93410020a0508dc341002')
WS = bytes.fromhex('0802101f1a020101220209052a02010132080000803f0000803f3a08000000000000000042086666e63e6666e63e4a02030352020000')
RE = [bytes.fromhex(s) for s in ('08031001', '08041002', '08051003', '08061002', '0807')]

def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

csvmulti = arg('--csv')
csvidx = int(arg('--index', '0'))
stop = int(arg('--stop', '270'))
if not csvmulti:
    raise SystemExit('pass --csv FILE --index N')
with open(csvmulti, newline='', encoding='utf-8') as _fh:
    _rows = [rr for rr in csv.DictReader(_fh) if rr.get('guid')]
if not 0 <= csvidx < len(_rows):
    raise SystemExit('row %d out of range (%d)' % (csvidx, len(_rows)))
row = _rows[csvidx]
GUID, SYSID, HOST = row['guid'], row['sysid'], row['host']

def varint_u64(n):
    n &= (1 << 64) - 1
    out = b''
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out += bytes([b | 0x80])
        else:
            return out + bytes([b])

c = [None]
sess = [None]

def connect_login():
    if c[0] is not None:
        try:
            c[0].close()
        except Exception:
            pass
    c[0] = Client(HOST, timeout=15)
    c[0].handshake()
    sess[0] = c[0].session
    fv = hashlib.sha1((sess[0] + X).encode()).hexdigest().upper()
    pw = hashlib.md5((sess[0] + GUID).encode()).hexdigest()
    c[0].req = 0
    c[0]._send('LOGIN', login_payload(GUID, pw, SYSID, fv))
    err = c[0]._recv().get(4, [None])[0]
    c[0].drain(timeout=2)
    return err is None

def raw(cmd, pay=None, timeout=14):
    c[0].req += 1
    send_frame(c[0].s, envelope(c[0].req, cmd, pay))
    o = c[0].s.gettimeout(); c[0].s.settimeout(timeout)
    try:
        _, fb = rd_frame(c[0].s)
    except Exception as e:
        return 999, 'TRANSPORT: %s' % e, b''
    finally:
        try:
            c[0].s.settimeout(o)
        except Exception:
            pass
    f = parse_fields(fb)
    e = f.get(4, [None])[0]
    et = f.get(5, [b''])[0]
    if isinstance(et, bytes):
        et = et.decode(errors='replace')
    return e, et.strip()[:300], (f.get(3, [b''])[0] if 3 in f else b'')

def bare():
    s = hashlib.sha1((sess[0] + D_SUM).encode()).hexdigest().upper()
    h = S.fstr(1, 'sum') + S.fstr(2, s)
    e, _, p = raw('get_player', S.fstr(1, CONFIG_VER) + fbytes(2, b'') + fbytes(3, h) + S.fstr(4, 'google Pixel 4') + S.fstr(5, '1.45.5'))
    if e is not None or not len(p):
        return None
    top = parse_fields(p)
    if 1 not in top or not isinstance(top[1][0], bytes):
        return None
    inner = parse_fields(top[1][0])
    sp = parse_fields(inner[1][0])
    qmap = {}
    try:
        qd = parse_fields(inner[36][0])
        for sdata in qd.get(1, []):
            m = parse_fields(sdata)
            for qq in m.get(2, []):
                n = parse_fields(qq)
                if 1 in n and not isinstance(n[1][0], bytes):
                    pr = n[4][0] if 4 in n and not isinstance(n[4][0], bytes) else 0
                    qmap[n[1][0]] = pr
    except Exception:
        pass
    return dict(R=inner.get(9, [0])[0], exp=inner.get(3, [0])[0] if 3 in inner else 0,
                lvl=sp.get(4, [1])[0], cur=list(inner.get(4, [])),
                inv=list(parse_fields(inner[7][0]).get(1, [])) if 7 in inner else [],
                ch=parse_fields(inner[35][0]).get(1, [0])[0] if 35 in inner else 0,
                daily=parse_fields(inner[37][0]).get(3, [0])[0] if 37 in inner else 0,
                qmap=qmap, inner=inner, sp=sp)

def submit(b, st0, E, decl, f6, rounds):
    if b in GENUINE:
        g = GEN[GENUINE[b]]
        F8 = [(a, bb) for a, bb in g['f8']]
        r = b''.join(S.fbytes(8, S.fvar(1, a) + (S.fvar(2, bb) if bb is not None else b'')) for a, bb in F8)
        f10b = bytes.fromhex(g['f10']) if g['f10'] else b''
        ff = (S.fvar(1, b) + S.fvar(4, g['f4']) + S.fvar(5, g['f5']) + S.fbytes(6, S.fvar(1, f6)) + S.fvar(7, g['f7']) + r + S.fbytes(10, f10b) + S.fbytes(13, bytes.fromhex(g['f13'])))
        if g['f14'] is not None:
            ff += S.fvar(14, g['f14'])
    else:
        g = GEN["45"]
        F8 = [(a, min(bb, CAP.get(a, lambda r: bb)(rounds)) if bb is not None else None) for a, bb in g['f8']]
        r = b''.join(S.fbytes(8, S.fvar(1, a) + (S.fvar(2, bb) if bb is not None else b'')) for a, bb in F8)
        ff = (S.fvar(1, b) + S.fvar(4, 1) + S.fvar(5, rounds) + S.fbytes(6, S.fvar(1, f6)) + S.fvar(7, rounds) + r + S.fbytes(10, b'') + S.fbytes(13, bytes.fromhex(g['f13']))) + S.fvar(14, 54)
    entry = S.fvar(1, E) + S.fstr(2, 'finish_fight') + S.fstr(3, CONFIG_VER) + S.fbytes(4, ff)
    curb = b''.join(S.fbytes(4, cc) for cc in st0['cur'])
    invb = S.fbytes(5, b''.join(S.fbytes(1, it) for it in st0['inv']))
    s7b = b''.join(S.fbytes(1, S.fvar(1, i) + S.fvar(2, v)) for i, v in sorted(st0['qmap'].items()))
    state = (S.fvar(1, E) + S.fvar(2, decl) + S.fvar(3, st0['lvl']) + curb + invb + varint((6 << 3) | 0) + varint_u64(st0['ch']) + S.fbytes(7, s7b) + S.fvar(8, st0['daily'] & MASK) + S.fbytes(9, S.fvar(1, 2) + S.fvar(2, 10)))
    return raw('process_offline_batch', S.fbytes(1, entry) + S.fbytes(2, state))

if not connect_login():
    print('LOGIN FAIL row=%d' % csvidx, flush=True)
    raise SystemExit(1)
todo = [b for b in CHAIN if b <= stop]
for b in todo:
    rounds = ROUNDS.get(b, 2)
    e0, t0, _ = raw('refresh_single_battle', S.fvar(1, b))
    if e0 is not None and ('No battle' in t0 or e0 == 1):
        print('b%d single not open (%r) — treat as done' % (b, t0[:80]), flush=True)
        continue
    t_single = int(time.time() * 1000)
    time.sleep(2.5)
    st0 = bare()
    if st0 is None:
        connect_login()
        st0 = bare()
        if st0 is None:
            print('bare dead at %d' % b, flush=True)
            raise SystemExit(1)
    E = st0['R'] + 1
    decl = st0['exp'] + 15
    f6 = t_single + 300
    e, t, _ = submit(b, st0, E, decl, f6, rounds)
    print('b%d fight=%s %s' % (b, e, t[:100]), flush=True)
    if 'No battle with modelId' in t:
        continue
    if e == 999:
        connect_login()
        st0 = bare()
        if st0 is None:
            print('bare dead at %d after relogin' % b, flush=True)
            raise SystemExit(1)
        E = st0['R'] + 1
        decl = st0['exp'] + 15
        e, t, _ = submit(b, st0, E, decl, f6, rounds)
        print('b%d retry fight=%s %s' % (b, e, t[:100]), flush=True)
        if e == 999:
            print('transport dead twice at %d' % b, flush=True)
            raise SystemExit(1)
    st1 = bare()
    if st1 is None:
        time.sleep(0.5)
        st1 = bare()
    if st1 is None:
        print('verify-fail at %d; continue' % b, flush=True)
        continue
    if st1['exp'] == st0['exp']:
        st0 = st1
        E = st0['R'] + 1
        decl = st0['exp'] + 15
        e, t, _ = submit(b, st0, E, decl, f6, rounds)
        print('b%d resubmit fight=%s %s' % (b, e, t[:100]), flush=True)
        st1 = bare()
        if st1 is None:
            continue
    print('b%d after R=%d exp=%d lvl=%d' % (b, st1['R'], st1['exp'], st1['lvl']), flush=True)

fe, ft, fpay = raw('faction_wars_get_state', b'')
print('faction pre err=%s' % fe, flush=True)
if fe is not None:
    print('UPGRADE FAIL still locked err=%s %s' % (fe, ft[:100]), flush=True)
    raise SystemExit(1)
raw('process_finished_features', b'')
se, st_, _ = raw('faction_wars_start_new_stage', b'')
print('start_new_stage err=%s' % se, flush=True)
raw('quest_refresh', bytes.fromhex('0a0107'))
ce, ct, _ = raw('faction_wars_choose_faction', S.fvar(1, 3))
print('choose_faction err=%s %s' % (ce, ct[:80]), flush=True)
fe2, _, fpay2 = raw('faction_wars_get_state', b'')
sel = None
try:
    m = parse_fields(fpay2)
    if 4 in m and isinstance(m[4][0], bytes):
        sel = parse_fields(m[4][0]).get(1, [None])[0]
except Exception:
    pass
print('selected=%s err=%s' % (sel, fe2), flush=True)
if sel != 3:
    print('UPGRADE FAIL select != 3', flush=True)
    raise SystemExit(1)
st = bare()
if st is not None and 13 in st['inner']:
    try:
        blob = parse_fields(st['inner'][13][0])[1][0]
        params = (S.fbytes(1, blob) + S.fvar(2, 1) + S.fvar(3, 2) + b''.join(S.fbytes(4, x) for x in RE) + S.fvar(5, 2) + S.fbytes(6, WI) + S.fbytes(7, WS))
        e, _, _ = raw('brawler_finish', params)
        print('stale-duel close err=%s' % e, flush=True)
    except Exception as ex:
        print('stale-close exc %s' % str(ex)[:80], flush=True)
fin = bare()
if fin is not None:
    coins = None
    for cc in fin['cur']:
        m = parse_fields(cc)
        if m.get(1, [None])[0] == 1:
            coins = m.get(2, [None])[0]
    print('DONE row=%d lvl=%s wins=%s coins=%s selected=3' % (csvidx, fin['lvl'], fin['inner'].get(16, [0])[0], coins), flush=True)
try:
    c[0].close()
except Exception:
    pass
