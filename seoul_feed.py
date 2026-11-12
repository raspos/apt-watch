"""Import a permitted Seoul listing delivery, against a declared complex roster."""
import argparse
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from apt_watch import DISTRICTS, ingest, store, ROOT

def import_delivery(db, manifest, batches, day, district=None):
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError("Use YYYY-MM-DD for the observation date")
    targets = {}
    for target in manifest:
        key = str(target['complex'] or '').strip()
        code = str(target['district'])
        if not key or key in targets or code not in DISTRICTS or not target['name'].strip():
            raise ValueError('Invalid or duplicate Seoul complex roster entry')
        targets[key] = {**target, 'district': code}
    if not targets:
        raise ValueError("Complex roster is empty")
    selected = {key for key,target in targets.items() if district is None or target['district']==district}
    validated = {}
    for batch in batches:
        key = str(batch['complex'] or '').strip()
        if key not in targets or key in validated:
            raise ValueError('Unknown or repeated complex in delivery')
        observed = datetime.fromisoformat(batch['observed'].replace('Z', '+00:00'))
        if not observed.tzinfo or observed.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()!=day:
            raise ValueError('Delivery observation date differs')
        if type(batch['success']) is not bool or not isinstance(batch['rows'],list):
            raise ValueError('Invalid delivery status')
        if batch['success'] and (type(batch.get('expectedCount')) is not int
                                 or batch['expectedCount'] != len(batch['rows'])
                                 or len({str(r['article_no']) for r in batch['rows']}) != len(batch['rows'])):
            raise ValueError('Incomplete or duplicate listing rows')
        target = targets[key]
        validated[key] = {**batch,'rows':[{**r,'district':target['district'],'complex_name':target['name']}
                                          for r in batch['rows']]}
    for key in sorted(selected & validated.keys()):
        ingest(db,validated[key])
    with db:
        for key in selected:
            payload=json.dumps(targets[key],ensure_ascii=False,sort_keys=True)
            existing=db.execute('SELECT payload FROM listing_roster WHERE day=? AND complex=?',(day,key)).fetchone()
            if existing and existing[0]!=payload:
                raise ValueError('Conflicting roster for the same observation day')
            db.execute('INSERT OR IGNORE INTO listing_roster VALUES (?,?,?,?)',
                       (day,key,targets[key]['district'],payload))
    stored = dict(db.execute('SELECT complex,success FROM batches WHERE day=?',(day,)))
    success = {key for key in selected if stored.get(key)==1}
    failed = {key for key in selected if stored.get(key)==0}
    listings = sum(n for key,n in db.execute('SELECT complex,COUNT(*) FROM listings WHERE day=? GROUP BY complex',(day,)) if key in success)
    return dict(day=day, rosterSize=len(targets), rosterDistricts=len({t['district'] for t in targets.values()}),
                selected=len(selected), success=len(success), failed=len(failed), missing=len(selected-success-failed),
                listings=listings, rosterCoverage=len(success)/len(selected) if selected else None)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--manifest',required=True,type=Path)
    p.add_argument('--feed',required=True,type=Path)
    p.add_argument('--day',required=True)
    p.add_argument('--district',choices=DISTRICTS)
    p.add_argument('--store',type=Path,default=ROOT/'data/history.sqlite3')
    args=p.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding='utf-8-sig'))
    batches=[json.loads(line) for line in args.feed.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    with store(args.store) as db:
        print(json.dumps(import_delivery(db,manifest,batches,args.day,args.district),ensure_ascii=False))
