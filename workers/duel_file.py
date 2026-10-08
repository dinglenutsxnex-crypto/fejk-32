"""duel_file.py — duel grind for ONE account read from a mint CSV file.
Same loop/failsafes as duel_burst.py (stuck-duel recovery, relogin,
per-60s board stop at top-outsider+GAP). No secrets needed (CSV is the input).
Usage: duel_file.py --file mint/eu-3.csv --minutes 15 [--max-wins 0] [--gap 50000] [--pace 0] [--jitter 0] [--loss-every 0]
(pace+jitter slow velocity to dodge flags; loss-every N loses every Nth duel
with a genuine-shaped loss so the account isn't a 100%-win metronome)
"""
import sys, time, hashlib, json, os, csv, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sf3 import Client, login_payload, envelope, send_frame, rd_frame, parse_fields, fvar, fbytes, ping_payload, D_SUM, CONFIG_VER
import sf3 as S

X = 'D61109D768EDAA3AD2EFA9EF357BD1AE33D5F0AB'
GAP = 50000
WI = bytes.fromhex('0a0508d10c10040a0508d20c10040a0508d93410020a0508dc341002')
WS = bytes.fromhex('0802101f1a020101220209052a02010132080000803f0000803f3a08000000000000000042086666e63e6666e63e4a02030352020000')
RE = [bytes.fromhex(s) for s in ('08031001', '08041002', '08051003', '08061002', '0807')]

def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

csvfile = arg('--file')
csvmulti = arg('--csv')
csvidx = int(arg('--index', '0'))
minutes = float(arg('--minutes', '15'))
maxwins = int(arg('--max-wins', '0'))
gap = int(arg('--gap', str(GAP)))
pace = float(arg('--pace', '0'))
jitter = float(arg('--jitter', '0'))
loss_every = int(arg('--loss-every', '0'))
LOSS = None
EXCLUDE = {name.strip().casefold() for name in os.environ.get('FLEET_NAMES', '').split(',') if name.strip()}
if csvmulti is not None:
    with open(csvmulti, newline='', encoding='utf-8') as _fh:
        _rows = [rr for rr in csv.DictReader(_fh) if rr.get('guid')]
    if not 0 <= csvidx < len(_rows):
        raise SystemExit('CSV row index %d out of range (rows=%d)' % (csvidx, len(_rows)))
    row = _rows[csvidx]
    csvfile = '%s#%d' % (csvmulti, csvidx)
else:
    if not csvfile:
        raise SystemExit('pass --csv FILE --index N or --file FILE')
    with open(csvfile, newline='', encoding='utf-8') as _fh:
        row = next(csv.DictReader(_fh))
GUID, SYSID, HOST = row['guid'], row['sysid'], row['host']
T_END = time.time() + minutes * 60

c = [None]
sess = [None]

def connect_login():
    # Never throws: False means dead route, caller decides (retry/exit).
    if c[0] is not None:
        try:
            c[0].close()
        except Exception:
            pass
    try:
        c[0] = Client(HOST, timeout=15)
        c[0].handshake()
        print('egress-node=%s' % (c[0].node if hasattr(c[0], 'node') else '?'), flush=True)
        sess[0] = c[0].session
        fv = hashlib.sha1((sess[0] + X).encode()).hexdigest().upper()
        pw = hashlib.md5((sess[0] + GUID).encode()).hexdigest()
        c[0].req = 0
        c[0]._send('LOGIN', login_payload(GUID, pw, SYSID, fv))
        err = c[0]._recv().get(4, [None])[0]
        c[0].drain(timeout=2)
        return err is None
    except Exception as ex:
        print('connect fail %s' % str(ex)[:100], flush=True)
        return False

def relogin():
    for _ in range(3):
        if connect_login():
            return True
        time.sleep(5)
    return False

def raw(cmd, pay=None):
    # Never throws: transport drops come back as 999 so the caller can
    # reinitialize the connection instead of dying mid-run.
    try:
        c[0].req += 1
        send_frame(c[0].s, envelope(c[0].req, cmd, pay))
    except Exception as ex:
        return 999, 'TRANSPORT: %s' % str(ex)[:100], b''
    o = c[0].s.gettimeout()
    try:
        c[0].s.settimeout(14)
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
    return e, (f.get(3, [b''])[0] if 3 in f else b''), b''

def is_clean():
    """True iff no open duel (f13 absent). None on unreadable state."""
    try:
        s = hashlib.sha1((sess[0] + D_SUM).encode()).hexdigest().upper()
        h = S.fstr(1, 'sum') + S.fstr(2, s)
        e, p, _ = raw('get_player', S.fstr(1, CONFIG_VER) + fbytes(2, b'') + fbytes(3, h) + S.fstr(4, 'google Pixel 4') + S.fstr(5, S.APP_VER))
        if e is not None or not len(p):
            return None
        top = parse_fields(p)
        if 1 not in top or not isinstance(top[1][0], bytes):
            return None
        return 13 not in parse_fields(top[1][0])
    except Exception:
        return None

def close_stale():
    # Finish processing is ASYNC: the reply acks instantly but f13/start
    # reflect the queue with lag (seconds-minutes under load). So: finish
    # ONCE per blob, then POLL for the apply — never rapid-fire finishes,
    # which only grow the queue and look like ignored acks.
    try:
        s = hashlib.sha1((sess[0] + D_SUM).encode()).hexdigest().upper()
        h = S.fstr(1, 'sum') + S.fstr(2, s)
        e, p, _ = raw('get_player', S.fstr(1, CONFIG_VER) + fbytes(2, b'') + fbytes(3, h) + S.fstr(4, 'google Pixel 4') + S.fstr(5, S.APP_VER))
        if e is not None or not len(p):
            print('close_stale: unreadable gp e=%s' % e, flush=True)
            return False
        top = parse_fields(p)
        if 1 not in top or not isinstance(top[1][0], bytes):
            return False
        inner = parse_fields(top[1][0])
        if 13 not in inner:
            return True
        blob = parse_fields(inner[13][0])[1][0]
        params = (fbytes(1, blob) + fvar(2, 1) + fvar(3, 2) + b''.join(fbytes(4, x) for x in RE) + fvar(5, 2) + fbytes(6, WI) + fbytes(7, WS))
        e, pr, _ = raw('brawler_finish', params)
        print('close_stale: finish e=%s pay=%d' % (e, len(pr)), flush=True)
        if e == 999:
            return False
    except Exception as ex:
        print('close_stale EXC %s' % str(ex)[:100], flush=True)
        return False
    for wait in (15, 20, 30, 30, 30):
        time.sleep(wait)
        clean = is_clean()
        print('close_stale: poll clean=%s' % clean, flush=True)
        if clean:
            return True
        if clean is None:
            relogin()
    return False

class _OnBoard(Exception):
    pass

t0 = time.time()
if not relogin():
    print('LOGIN FAIL %s (route dead after retries)' % csvfile, flush=True)
    raise SystemExit(1)
PID = None
for _ in range(3):
    s = hashlib.sha1((sess[0] + D_SUM).encode()).hexdigest().upper()
    h = S.fstr(1, 'sum') + S.fstr(2, s)
    e, p, _ = raw('get_player', S.fstr(1, CONFIG_VER) + fbytes(2, b'') + fbytes(3, h) + S.fstr(4, 'google Pixel 4') + S.fstr(5, S.APP_VER))
    if e == 999:
        if not relogin():
            break
        continue
    try:
        top = parse_fields(p)
        if 1 in top and isinstance(top[1][0], bytes):
            PID = parse_fields(parse_fields(top[1][0])[1][0])[1][0]
            print('pid=%s' % PID, flush=True)
            break
    except Exception as ex:
        print('pid-resolve fail %s' % str(ex)[:80], flush=True)
        break
    print('pid-resolve empty (e=%s); relogin' % e, flush=True)
    if not relogin():
        break
if PID is None:
    print('PID FAIL %s (account flagged? route dead?)' % csvfile, flush=True)
    raise SystemExit(1)
for _ in range(2):
    clean = is_clean()
    if clean:
        break
    print('startup wedge detected; close+patient-verify', flush=True)
    close_stale()
else:
    clean = is_clean()
if not clean:
    print('STARTUP WEDGE STUCK %s; giving up slot early' % csvfile, flush=True)
    raise SystemExit(3)
wins = fails = i = 0
losses_around = 0
consec_fail = 0
last_board = 0
try:
    while time.time() < T_END and (maxwins <= 0 or wins < maxwins):
        i += 1
        ok = False
        fail_why = 'unknown'
        for att in range(3):
            if i % 10 == 1 and att == 0:
                try:
                    c[0]._send('ping', ping_payload(sess[0]))
                    c[0]._recv()
                except Exception:
                    pass
            e, p, _ = raw('brawler_start', None)
            if e == 999:
                # Drop before the server saw anything: fresh session, redo once.
                if not relogin():
                    fail_why = 'start-transport-dead'
                    break
                e, p, _ = raw('brawler_start', None)
                if e == 999:
                    fail_why = 'start-transport-dead-x2'
                    break
            if e == 50003:
                # May be a genuinely open duel OR lagging async state.
                # Wait it out first (a blind close+restart cycle is what
                # wedged the whole AS fleet); only close if it persists.
                time.sleep(20)
                e2, p2, _ = raw('brawler_start', None)
                if e2 is None and len(p2):
                    e, p = e2, p2
                else:
                    if not close_stale():
                        fail_why = 'start-50003-stuck'
                        time.sleep(60)
                        break
                    fail_why = 'start-50003-wedged'
                    time.sleep(10)
                    continue
            if e is not None or not len(p):
                if e is None:
                    fail_why = 'start-empty'
                    break
                fail_why = 'start-err-%s' % e
                if not relogin():
                    fail_why = 'relogin-dead'
                    break
                continue
            try:
                blob = parse_fields(p)[1][0]
            except Exception:
                fail_why = 'blob-parse'
                break
                # Humanization: mostly 2-0 wins, every loss_every-th duel is a
                # minimal genuine-shaped loss (duel_api sec 7). Identical
                # always-win metronomes are what got the last fleet flagged.
                is_loss = loss_every > 0 and (wins + losses_around) % loss_every == loss_every - 1
                if is_loss:
                    params = fbytes(1, blob) + fvar(2, 2) + fvar(3, 2)
                else:
                    params = (fbytes(1, blob) + fvar(2, 1) + fvar(3, 2) + b''.join(fbytes(4, x) for x in RE) + fvar(5, 2) + fbytes(6, WI) + fbytes(7, WS))
                e, pr, _ = raw('brawler_finish', params)
                if e == 999:
                    # Finish may or may not have reached the server — check
                    # state instead of guessing (blind re-start self-wedges).
                    if not relogin():
                        fail_why = 'finish-transport-dead'
                        break
                    st = is_clean()
                    if st is None:
                        fail_why = 'finish-state-unknown'
                        break
                    if st:
                        continue  # finish landed -> fresh start next att
                    if close_stale():
                        continue  # closed -> fresh start next att
                    fail_why = 'finish-wedge-stuck'
                    time.sleep(30)
                    break
                if e is None and len(pr):
                    if is_loss:
                        losses_around += 1
                    else:
                        wins += 1
                    ok = True
                    consec_fail = 0
                    if pace > 0 or jitter > 0:
                        time.sleep(pace + random.uniform(0, jitter))
                    break
                fail_why = 'finish-err-%s' % e
                if not relogin():
                    fail_why = 'finish-relogin-dead'
                    break
                break
            except Exception as ex:
                print('duel EXC %s; relogin' % str(ex)[:80], flush=True)
                fail_why = 'exc'
                if not relogin():
                    fail_why = 'exc-relogin-dead'
                    break
                time.sleep(2)
                continue
        if not ok:
            fails += 1
            consec_fail += 1
            if fail_why == 'unknown':
                fail_why = 'atts-exhausted'
            print('fail i=%d why=%s wins=%d' % (i, fail_why, wins), flush=True)
            if consec_fail >= 15:
                print('WEDGED %d consecutive fails (account flagged?); giving up slot' % consec_fail, flush=True)
                break
            time.sleep(5)
        if i % 25 == 0:
            el = int(time.time() - t0)
            print('duels=%d wins=%d losses=%d fails=%d %ds left=%ds' % (i, wins, losses_around, fails, el, max(0, int(T_END - time.time()))), flush=True)
        if PID is not None and int(time.time() - last_board) >= 60:
            last_board = time.time()
            # Read-only: NEVER reconnect here. A dead board read must not
            # disturb a healthy duel session (that was the handshake spam).
            try:
                e, p, _ = raw('get_leaderboards', fvar(1, 322))
                if e == 999 or e is not None or not len(p):
                    print('board-check skip (e=%s)' % e, flush=True)
                else:
                    try:
                        rows = parse_fields(parse_fields(p)[2][0])[1]
                    except Exception as ex:
                        print('board-check parse fail %s' % str(ex)[:80], flush=True)
                        rows = []
                    if not rows:
                        print('board-check empty rows', flush=True)
                    mine = (None, None)
                    top_out = ('?', 0)
                    for k, r in enumerate(rows):
                        m = parse_fields(r)
                        nm = m.get(2, [b''])[0]
                        nm = nm.decode(errors='replace') if isinstance(nm, bytes) else str(nm)
                        rt = m.get(4, [0])[0]
                        if m.get(1, [None])[0] == PID:
                            mine = (k + 1, rt)
                        elif nm.lower() not in EXCLUDE and isinstance(rt, int) and rt > top_out[1]:
                            top_out = (nm[:20].encode('ascii', 'replace').decode(), rt)
                    tgt = top_out[1] + gap
                    print('rank=%s rating=%s top-out=%s/%s target=%s' % (mine[0], mine[1], top_out[0], top_out[1], tgt), flush=True)
                    if mine[0] is not None and isinstance(mine[1], int) and mine[1] >= tgt:
                        print('TARGET %d REACHED STOPPING' % tgt, flush=True)
                        raise _OnBoard()
            except _OnBoard:
                raise
            except Exception as ex:
                print('board-check fail %s' % str(ex)[:80], flush=True)
except _OnBoard:
    print('onboard-target, stopping early', flush=True)
try:
    c[0].close()
except Exception:
    pass
print('DONE wins=%d losses=%d fails=%d duels=%d wall=%ds file=%s' % (wins, losses_around, fails, i, int(time.time() - t0), csvfile), flush=True)
