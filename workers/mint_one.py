"""mint_one.py — mint a faction-ready account: handshake/login/create_player,
full chain 10->270 (faction unlock at 270/lvl7) + faction select(3) +
probe-duel verify. Writes one CSV row.
Usage: mint_one.py --server eu --out mint/eu-3.csv [--name NXYZ]
Servers: eu, us, tokyo, mumbai, sg (sg routes to Tokyo nodes).
"""
import sys, time, hashlib, json, random, uuid, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sf3 import Client, login_payload, envelope, send_frame, rd_frame, parse_fields, varint, fvar, fstr, fbytes, ping_payload, D_SUM, CONFIG_VER
import sf3 as S

X = 'D61109D768EDAA3AD2EFA9EF357BD1AE33D5F0AB'
HOSTS = {
    'eu': ['54.246.136.56'],
    'us': ['ec2-34-215-125-222.us-west-2.compute.amazonaws.com'],
    'tokyo': ['ec2-35-73-37-159.ap-northeast-1.compute.amazonaws.com'],
    'mumbai': ['52.66.28.201'],
    'sg': ['ec2-35-73-37-159.ap-northeast-1.compute.amazonaws.com'],
    'in': ['52.66.28.201'],
    'as': ['ec2-35-73-37-159.ap-northeast-1.compute.amazonaws.com'],
}
MASK = (1 << 64) - 1
# genuine fight bytes (VM capture rid48/89/127/168 + b36/b40)
GEN = {
    10: {'f4': 1, 'f5': 1, 'f7': 1, 'f8': [(1, 6), (3, 3), (4, 1), (5, 3), (6, None), (7, None)], 'f10': '', 'f13': '103b1a01002201312a02840132049060663f3a040000000042040852073e4a0112520106', 'f14': None},
    20: {'f4': 1, 'f5': 2, 'f7': 2, 'f8': [(1, 8), (3, 3), (5, 3), (6, None), (7, None), (4, 1)], 'f10': '', 'f13': '10451a020000220222152a023622320866fc6b3f18476b3f3a080000000000000000420861f85e3ed0f73b3e4a02090752020703', 'f14': None},
    30: {'f4': 1, 'f5': 2, 'f7': 2, 'f8': [(1, 3), (2, 3), (5, 3), (6, None), (7, None), (4, 1)], 'f10': '', 'f13': '103f1a0200002202171a2a0236313208438b7c3f2cb2593f3a08000000000000000042080cde7e3e295c4f3e4a02070852020202', 'f14': None},
    35: {'f4': 1, 'f5': 2, 'f7': 2, 'f8': [(1, 6), (3, 3), (4, 2), (5, 3), (6, None), (7, None), (2, 1)], 'f10': '', 'f13': '0830104e1a020f21220215272a0247713208cfe97c3fb9c6d73e3a08000000000000000042086dc6103e44413d3e4a020d095202010c', 'f14': 48},
    36: {'f4': 1, 'f5': 2, 'f7': 2, 'f8': [(1, 6), (4, 1), (6, None), (7, None), (2, 3)], 'f10': '', 'f13': '0833104d1a02191a22021e1f2a025c5732083b50533f8e71e73e3a08000000000000000042085c12143e14ae473e4a02120b52020205', 'f14': 51},
    40: {'f4': 1, 'f5': 3, 'f7': 3, 'f8': [(1, 14), (4, 3), (5, 6), (6, None), (7, None), (2, 6), (3, 4)], 'f10': '', 'f13': '08970110c0011a032c2f3c22033034422a06bd01c0019102320c29eb433fc5b8243ffc3afd3e3a0c000000000000000000000000420c58f09c3df0f6bd3d54f09c3d4a031b181c520306070c', 'f14': 151},
}
SRC45 = {'f8': [(1, 8), (2, 3), (3, 3), (4, 2), (5, 4), (6, None), (7, None)], 'f13': '083610551a021e18220226202a026d653208432b183f52387d3f3a080000000000000000420860d10a3e68ee723e4a02101352020501'}
CAP = {1: lambda r: 50 * r, 2: lambda r: 5 * r, 3: lambda r: 50 * r, 4: lambda r: 1 * r, 5: lambda r: 50, 6: lambda r: 1 * r, 7: lambda r: 1 * r}

def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

server = arg('--server', 'eu')
out = arg('--out', 'mint-eu-0.csv')
fixed_name = arg('--name')
HOST = HOSTS[server][0]

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

def connect_login(guid=None, sysid=None):
    if c[0] is not None:
        try:
            c[0].close()
        except Exception:
            pass
    c[0] = Client(HOST, timeout=15)
    c[0].handshake()
    sess[0] = c[0].session
    if guid is None:
        return True
    fv = hashlib.sha1((sess[0] + X).encode()).hexdigest().upper()
    pw = hashlib.md5((sess[0] + guid).encode()).hexdigest()
    c[0].req = 0
    c[0]._send('LOGIN', login_payload(guid, pw, sysid, fv))
    err = c[0]._recv().get(4, [None])[0]
    c[0].drain(timeout=2)
    return err is None

def raw(cmd, pay=None):
    c[0].req += 1
    send_frame(c[0].s, envelope(c[0].req, cmd, pay))
    o = c[0].s.gettimeout(); c[0].s.settimeout(14)
    try:
        _, fb = rd_frame(c[0].s)
    finally:
        c[0].s.settimeout(o)
    f = parse_fields(fb)
    e = f.get(4, [None])[0]
    et = f.get(5, [b''])[0]
    if isinstance(et, bytes):
        et = et.decode(errors='replace')
    return e, et.strip()[:200], (f.get(3, [b''])[0] if 3 in f else b'')

def bare():
    s = hashlib.sha1((sess[0] + D_SUM).encode()).hexdigest().upper()
    h = S.fstr(1, 'sum') + S.fstr(2, s)
    e, et, p = raw('get_player', S.fstr(1, CONFIG_VER) + fbytes(2, b'') + fbytes(3, h) + S.fstr(4, 'google Pixel 4') + S.fstr(5, '1.45.5'))
    if e is not None or not len(p):
        return None
    top = parse_fields(p)
    if 1 not in top or not isinstance(top[1][0], bytes):
        return None
    inner = parse_fields(top[1][0])
    sp = parse_fields(inner[1][0])
    return dict(R=inner.get(9, [0])[0], exp=inner.get(3, [0])[0] if 3 in inner else 0,
                lvl=sp.get(4, [1])[0], cur=list(inner.get(4, [])),
                inv=list(parse_fields(inner[7][0]).get(1, [])),
                ch=parse_fields(inner[35][0]).get(1, [0])[0],
                daily=parse_fields(inner[37][0]).get(3, [0])[0])

def appearance():
    import struct as st
    ch = S.fvar(1, 30) + varint((2 << 3) | 1) + st.pack('<d', 0.05)
    cs = S.fvar(1, 1) + varint((2 << 3) | 1) + st.pack('<d', 0.15)
    return S.fvar(1, 1) + S.fvar(2, 2) + S.fbytes(3, ch) + S.fbytes(4, cs) + S.fvar(5, 7)

connect_login()
guid = str(__import__('uuid').uuid4())
sysid = ''.join(random.choice('0123456789abcdef') for _ in range(15))
name = fixed_name or ('N' + ''.join(random.choice('ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(7)))
if not connect_login(guid, sysid):
    print('MINT LOGIN FAIL', flush=True)
    raise SystemExit(1)
c[0]._send('ping', ping_payload(sess[0]))
try:
    c[0]._recv()
except Exception:
    pass
sv = hashlib.sha1((sess[0] + D_SUM).encode()).hexdigest().upper()
h = S.fstr(1, 'sum') + S.fstr(2, sv)
cp = (S.fstr(1, name) + S.fbytes(2, appearance()) + S.fstr(3, CONFIG_VER)
      + S.fbytes(4, S.fstr(1, 'dojo') + S.fstr(2, '1.1'))
      + S.fbytes(4, S.fstr(1, 'CREG') + S.fstr(2, str(int(time.time()))))
      + S.fbytes(5, h) + S.fstr(6, S.APP_VER))
e, et, p = raw('create_player', cp)
print('create err=%s name=%s' % (e, name), flush=True)
if e is not None or not len(p):
    print('MINT FAIL', flush=True)
    raise SystemExit(1)

ROUNDS = {10: 1, 20: 2, 30: 2, 35: 2, 36: 2, 40: 3, 45: 2, 46: 2, 48: 2, 50: 1, 60: 3, 70: 2, 80: 2, 90: 2, 95: 2, 100: 3, 150: 3, 210: 3, 270: 3}
BATTLES = [10, 20, 30, 35, 36, 40, 45, 46, 48, 50, 60, 70, 80, 90, 95, 100, 110, 120, 130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 270]
unlocked = None
for b in BATTLES:
    rounds = ROUNDS.get(b, 2)
    if b != 10:
        raw('refresh_single_battle', S.fvar(1, b))
        t_single = int(time.time() * 1000)
        time.sleep(2.5)
    st0 = bare()
    if st0 is None:
        connect_login(guid, sysid)
        st0 = bare()
        if st0 is None:
            print('bare dead at %d' % b, flush=True)
            break
    E = st0['R'] + 1
    decl = 20 if b == 10 else st0['exp'] + 15
    f6 = int(time.time() * 1000) - 2200 if b == 10 else t_single + 300
    via = 'gp' if b == 10 else 'pob'
    if b in GEN:
        g = GEN[b]
        F8 = [(a, bb) for a, bb in g['f8']]
        r = b''.join(S.fbytes(8, S.fvar(1, a) + (S.fvar(2, bb) if bb is not None else b'')) for a, bb in F8)
        f10b = bytes.fromhex(g['f10']) if g['f10'] else b''
        ff = (S.fvar(1, b) + S.fvar(4, g['f4']) + S.fvar(5, g['f5']) + S.fbytes(6, S.fvar(1, f6)) + S.fvar(7, g['f7']) + r + S.fbytes(10, f10b) + S.fbytes(13, bytes.fromhex(g['f13'])))
        if g['f14'] is not None:
            ff += S.fvar(14, g['f14'])
    else:
        F8 = [(a, min(bb, CAP.get(a, lambda r: bb)(rounds)) if bb is not None else None) for a, bb in SRC45['f8']]
        r = b''.join(S.fbytes(8, S.fvar(1, a) + (S.fvar(2, bb) if bb is not None else b'')) for a, bb in F8)
        ff = (S.fvar(1, b) + S.fvar(4, 1) + S.fvar(5, rounds) + S.fbytes(6, S.fvar(1, f6)) + S.fvar(7, rounds) + r + S.fbytes(10, b'') + S.fbytes(13, bytes.fromhex(SRC45['f13']))) + S.fvar(14, 54)
    entry = S.fvar(1, E) + S.fstr(2, 'finish_fight') + S.fstr(3, CONFIG_VER) + S.fbytes(4, ff)
    curb = b''.join(S.fbytes(4, cc) for cc in st0['cur'])
    invb = S.fbytes(5, b''.join(S.fbytes(1, it) for it in st0['inv']))
    state = (S.fvar(1, E) + S.fvar(2, decl) + S.fvar(3, st0['lvl']) + curb + invb + varint((6 << 3) | 0) + varint_u64(st0['ch']) + S.fbytes(7, b'') + S.fvar(8, st0['daily'] & MASK) + S.fbytes(9, S.fvar(1, 2) + S.fvar(2, 10)))
    if via == 'gp':
        sv2 = hashlib.sha1((sess[0] + D_SUM).encode()).hexdigest().upper()
        hh = S.fstr(1, 'sum') + S.fstr(2, sv2)
        pay = S.fstr(1, CONFIG_VER) + S.fbytes(2, S.fbytes(1, entry) + S.fbytes(2, state)) + S.fbytes(3, hh) + S.fstr(4, 'google Pixel 4') + S.fstr(5, '1.45.5')
        e, et, p = raw('get_player', pay)
    else:
        e, et, p = raw('process_offline_batch', S.fbytes(1, entry) + S.fbytes(2, state))
    be, bet, bp = raw('brawler_start', None)
    print('b%d fight=%s brawler=%s' % (b, e, be), flush=True)
    if be is None:
        # brawler open from 36 on; close the probe duel immediately so the
        # account stays clean, but KEEP CHAINING to 270 (faction unlock).
        blob = parse_fields(bp)[1][0]
        WIN_STATS = bytes.fromhex('0802101f1a020101220209052a02010132080000803f0000803f3a08000000000000000042086666e63e6666e63e4a02030352020000')
        WIN_ITEMS = bytes.fromhex('0a0508d10c10040a0508d20c10040a0508d93410020a0508dc341002')
        RENT = [bytes.fromhex(s) for s in ('08031001', '08041002', '08051003', '08061002', '0807')]
        params = (S.fbytes(1, blob) + S.fvar(2, 1) + S.fvar(3, 2) + b''.join(S.fbytes(4, x) for x in RENT) + S.fvar(5, 2) + S.fbytes(6, WIN_ITEMS) + S.fbytes(7, WIN_STATS))
        fe, fet, fp = raw('brawler_finish', params)
        print('probe-duel closed err=%s at %d' % (fe, b), flush=True)
        if unlocked is None:
            unlocked = b
    time.sleep(0.5)
# faction select (required: locked 1200005 until 270/lvl7)
raw('process_finished_features', b'')
se, set_, _ = raw('faction_wars_start_new_stage', b'')
print('start_new_stage err=%s' % se, flush=True)
raw('quest_refresh', bytes.fromhex('0a0107'))
ce, cet, _ = raw('faction_wars_choose_faction', S.fvar(1, 3))
print('choose_faction(3) err=%s %s' % (ce, cet[:80]), flush=True)
fe, fet, fpay = raw('faction_wars_get_state', b'')
sel = None
try:
    _m = parse_fields(fpay)
    if 4 in _m and isinstance(_m[4][0], bytes):
        sel = parse_fields(_m[4][0]).get(1, [None])[0]
except Exception:
    pass
print('faction selected=%s err=%s' % (sel, fe), flush=True)
if sel != 3:
    print('MINT WARN faction select != 3 (locked?)', flush=True)
d = os.path.dirname(os.path.abspath(out))
os.makedirs(d, exist_ok=True)
with open(out, 'w') as fh:
    fh.write('name,guid,sysid,host\n')
    fh.write('%s,%s,%s,%s\n' % (name, guid, sysid, HOST))
print('WROTE %s unlocked=%s' % (out, unlocked), flush=True)
try:
    c[0].close()
except Exception:
    pass
