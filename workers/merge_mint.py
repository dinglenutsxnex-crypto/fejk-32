"""merge_mint.py — combine per-worker mint CSVs into one mint/mint-<server>.csv,
appending to the existing file (dedupe by guid).
Usage: merge_mint.py --server eu --glob 'staging/**/w-*.csv' --out mint/mint-eu.csv
"""
import sys
import csv
import glob as _glob
import os


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


server = arg('--server', 'eu')
pattern = arg('--glob', 'staging/**/w-*.csv')
out = arg('--out', 'mint/mint-%s.csv' % server)

seen = {}
if os.path.exists(out):
    with open(out, newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            if r.get('guid'):
                seen[r['guid']] = r

added = 0
import glob as gmod
files = sorted(gmod.glob(pattern, recursive=True))
print('merging %d files' % len(files), flush=True)
for fp in files:
    try:
        with open(fp, newline='', encoding='utf-8') as fh:
            for r in csv.DictReader(fh):
                if r.get('guid') and r['guid'] not in seen:
                    seen[r['guid']] = {
                        'name': r.get('name', ''),
                        'guid': r['guid'],
                        'sysid': r.get('sysid', ''),
                        'host': r.get('host', ''),
                    }
                    added += 1
    except Exception as ex:
        print('skip %s: %s' % (fp, str(ex)[:80]), flush=True)
os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
if not seen:
    print('NO ROWS merged; refusing to write empty %s' % out, flush=True)
    raise SystemExit(1)
with open(out, 'w', newline='', encoding='utf-8') as fh:
    w = csv.DictWriter(fh, fieldnames=['name', 'guid', 'sysid', 'host'])
    w.writeheader()
    for guid, r in seen.items():
        w.writerow(r)
print('wrote %s total=%d added=%d' % (out, len(seen), added), flush=True)
