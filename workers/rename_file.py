"""rename_file.py — rename ONE mint-CSV account to a picked fleet name.
1.46 recipe (FINAL_REPORT sec 9): direct change_appearance{f1: Currency
{f1:2, f2:cost}, f2: name}. Tries cost 0 (first rename free), falls back to
cost 10 on Invalid-currency. Verifies via get_player ShortPlayer.f2.
Usage: rename_file.py --csv mint/mint-eu.csv --index N --names "a,b,c"
Name for this worker: names[index % len(names)] (even deterministic split).
"""
import sys, time, hashlib, random, os, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sf3 import Client, login_payload, envelope, send_frame, rd_frame, parse_fields, fvar, fbytes, D_SUM, CONFIG_VER
import sf3 as S

X = 'D61109D768EDAA3AD2EFA9EF357BD1AE33D5F0AB'

def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

csvmulti = arg('--csv')
csvidx = int(arg('--index', '0'))
names = [n.strip() for n in (arg('--names', '') or '').split(',') if n.strip()]
if not csvmulti:
    raise SystemExit('pass --csv FILE --index N --names "a,b,c"')
if not names:
    raise SystemExit('no names given')
with open(csvmulti, newline='', encoding='utf-8') as _fh:
    _rows = [rr for rr in csv.DictReader(_fh) if rr.get('guid')]
if not 0 <= csvidx < len(_rows):
    raise SystemExit('row %d out of range (%d)' % (csvidx, len(_rows)))
row = _rows[csvidx]
GUID, SYSID, HOST = row['guid'], row['sysid'], row['host']
NAME = names[csvidx % len(names)]
if len(NAME) > 20:
    raise SystemExit('name too long (%d chars, max 20): %r' % (len(NAME), NAME))

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
    try:
        c[0].req += 1
        send_frame(c[0].s, envelope(c[0].req, cmd, pay))
    except Exception as ex:
        return 999, 'TRANSPORT: %s' % str(ex)[:100], b''
    o = c[0].s.gettimeout()
    try:
        c[0].s.settimeout(timeout)
    except Exception as ex:
        return 999, 'TRANSPORT: %s' % str(ex)[:100], b''
    try:
        _, fb = rd_frame(c[0].s)
    except Exception as ex:
        return 999, 'TRANSPORT: %s' % str(ex)[:100], b''
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
    return e, et.strip()[:200], (f.get(3, [b''])[0] if 3 in f else b'')

def player_name():
    for _ in range(3):
        s = hashlib.sha1((sess[0] + D_SUM).encode()).hexdigest().upper()
        h = S.fstr(1, 'sum') + S.fstr(2, s)
        e, _, p = raw('get_player', S.fstr(1, CONFIG_VER) + fbytes(2, b'') + fbytes(3, h) + S.fstr(4, 'google Pixel 4') + S.fstr(5, S.APP_VER))
        if e == 999:
            if not connect_login():
                return None
            continue
        if e is not None or not len(p):
            return None
        top = parse_fields(p)
        if 1 not in top or not isinstance(top[1][0], bytes):
            return None
        sp = parse_fields(parse_fields(top[1][0])[1][0])
        nm = sp.get(2, [b''])[0]
        return nm.decode('utf8', 'replace') if isinstance(nm, bytes) else str(nm)
    return None

for attempt in range(3):
    if connect_login():
        break
    time.sleep(5)
else:
    print('LOGIN FAIL row=%d' % csvidx, flush=True)
    raise SystemExit(1)

before = player_name()
esc = lambda x: x.encode('unicode_escape').decode() if isinstance(x, str) else x
print('row=%d before=%s want=%s' % (csvidx, esc(before), esc(NAME)), flush=True)
if before == NAME:
    print('ALREADY row=%d' % csvidx, flush=True)
    raise SystemExit(0)

applied = False
last_err_text = ''
for cost in (0, 10):
    e, t, _ = raw('change_appearance', S.fbytes(1, S.fvar(1, 2) + S.fvar(2, cost)) + S.fstr(2, NAME))
    last_err_text = t
    print('row=%d cost=%d err=%s %s' % (csvidx, cost, e, t[:120]), flush=True)
    if e == 999:
        if connect_login():
            e, t, _ = raw('change_appearance', S.fbytes(1, S.fvar(1, 2) + S.fvar(2, cost)) + S.fstr(2, NAME))
            last_err_text = t
            print('row=%d cost=%d retry err=%s %s' % (csvidx, cost, e, t[:120]), flush=True)
    if e is None:
        applied = True
        break
    if 'Invalid currency' not in t:
        break
    time.sleep(1)

time.sleep(1)
after = player_name()
print('row=%d after=%s' % (csvidx, esc(after)), flush=True)
if after == NAME:
    print('RENAMED row=%d %s' % (csvidx, esc(NAME)), flush=True)
elif 'censor' in last_err_text.casefold():
    # Known outcome, not a failure: name stays, nothing charged.
    print('CENSORED row=%d %s (kept %s)' % (csvidx, esc(NAME), esc(after)), flush=True)
else:
    print('NOT-APPLIED row=%d err=%s' % (csvidx, last_err_text[:120]), flush=True)
    raise SystemExit(2)
try:
    c[0].close()
except Exception:
    pass
