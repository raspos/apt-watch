"""Analyze Identical Listing Price Changes between 2026-11-12 and 2026-11-13.
Computes exact DoD price dynamics for identical listings:
- Total identical listings
- Price cuts, price hikes, unchanged listings
- Median percentage change for cuts and hikes
- New entrants (13th new) and exits (12th dropped)
Saves results to data/identical_listings_dod_report.json.
"""

import json
import sqlite3
from pathlib import Path
from statistics import median, mean

ROOT = Path(__file__).resolve().parent.parent

def run_identical_listings_audit():
    db_path = ROOT / 'data' / 'history.sqlite3'
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Load 2026-11-12 listings
    cur.execute("SELECT complex, id, price, payload FROM listings WHERE day = '2026-11-12'")
    rows_12 = cur.fetchall()
    listings_12 = {}
    for c, lid, p, payload_str in rows_12:
        key = f"{c}_{lid}"
        payload = json.loads(payload_str) if payload_str else {}
        listings_12[key] = {
            'complex': c,
            'id': lid,
            'price': float(p),
            'payload': payload
        }

    # Load 2026-11-13 listings
    cur.execute("SELECT complex, id, price, payload FROM listings WHERE day = '2026-11-13'")
    rows_13 = cur.fetchall()
    listings_13 = {}
    for c, lid, p, payload_str in rows_13:
        key = f"{c}_{lid}"
        payload = json.loads(payload_str) if payload_str else {}
        listings_13[key] = {
            'complex': c,
            'id': lid,
            'price': float(p),
            'payload': payload
        }

    keys_12 = set(listings_12.keys())
    keys_13 = set(listings_13.keys())

    identical_keys = keys_12.intersection(keys_13)
    new_keys = keys_13 - keys_12
    dropped_keys = keys_12 - keys_13

    price_cuts = []
    price_hikes = []
    price_unchanged = []

    for k in identical_keys:
        p12 = listings_12[k]['price']
        p13 = listings_13[k]['price']
        diff = p13 - p12
        pct_change = ((p13 - p12) / p12) * 100.0

        item = {
            'complex': listings_13[k]['complex'],
            'id': listings_13[k]['id'],
            'p12': p12,
            'p13': p13,
            'diff': diff,
            'pctChange': round(pct_change, 3)
        }

        if p13 < p12:
            price_cuts.append(item)
        elif p13 > p12:
            price_hikes.append(item)
        else:
            price_unchanged.append(item)

    n_identical = len(identical_keys)
    n_cuts = len(price_cuts)
    n_hikes = len(price_hikes)
    n_unchanged = len(price_unchanged)
    n_new = len(new_keys)
    n_dropped = len(dropped_keys)

    cut_pcts = [x['pctChange'] for x in price_cuts]
    hike_pcts = [x['pctChange'] for x in price_hikes]

    median_cut_pct = round(median(cut_pcts), 2) if cut_pcts else 0.0
    mean_cut_pct = round(mean(cut_pcts), 2) if cut_pcts else 0.0
    median_hike_pct = round(median(hike_pcts), 2) if hike_pcts else 0.0
    mean_hike_pct = round(mean(hike_pcts), 2) if hike_pcts else 0.0

    report = {
        'targetDate': '2026-11-13',
        'comparisonDate': '2026-11-12',
        'totalListings12': len(listings_12),
        'totalListings13': len(listings_13),
        'identicalListingsCount': n_identical,
        'identicalShareOf12': round((n_identical / len(listings_12)) * 100.0, 2) if listings_12 else 0.0,
        'identicalShareOf13': round((n_identical / len(listings_13)) * 100.0, 2) if listings_13 else 0.0,
        'breakdown': {
            'priceCuts': {
                'count': n_cuts,
                'ratioPercent': round((n_cuts / n_identical) * 100.0, 2) if n_identical else 0.0,
                'medianChangePercent': median_cut_pct,
                'meanChangePercent': mean_cut_pct,
                'sampleTopCuts': sorted(price_cuts, key=lambda x: x['diff'])[:5]
            },
            'priceHikes': {
                'count': n_hikes,
                'ratioPercent': round((n_hikes / n_identical) * 100.0, 2) if n_identical else 0.0,
                'medianChangePercent': median_hike_pct,
                'meanChangePercent': mean_hike_pct,
                'sampleTopHikes': sorted(price_hikes, key=lambda x: x['diff'], reverse=True)[:5]
            },
            'priceUnchanged': {
                'count': n_unchanged,
                'ratioPercent': round((n_unchanged / n_identical) * 100.0, 2) if n_identical else 0.0
            }
        },
        'turnover': {
            'newListingsCount': n_new,
            'droppedListingsCount': n_dropped
        }
    }

    out_path = ROOT / 'data' / 'identical_listings_dod_report.json'
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print("Identical Listings Report written to:", out_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    conn.close()
    return report

if __name__ == '__main__':
    run_identical_listings_audit()
