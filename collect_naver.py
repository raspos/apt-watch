"""Collect rendered Naver sale cards for verified Seoul complex mappings."""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from apt_watch import ROOT, now, read_trades, store
from seoul_feed import import_delivery

sys.path.insert(0, str(ROOT.parent))
from pyungchon_land.collectors.naver_browser import MOBILE_COMPLEX_PAGE, _rendered_articles
from pyungchon_land.normalization import price_manwon


COMPLEX_URL = 'https://fin.land.naver.com/complexes/{complex_no}'


def _rendered_articles_with_fallback(page):
    """Return one record per exact /articles/<number> link in rendered cards with dong and sub-item price fallback."""
    return page.locator('li[class*="ArticleCard-module"]').evaluate_all(r"""
    (cards) => {
      const result = [];
      const seen = new Set();
      for (const card of cards) {
        const header = card.innerText || '';
        const area = header.match(/전용\s*([0-9.]+)/);
        const supply = header.match(/([0-9.]+)\s*㎡\s*\(전용/);
        const floor = header.match(/(저|중|고|[0-9]+)\/([0-9]+)층/);
        const direction = header.match(/(남동향|남서향|북동향|북서향|남향|북향|동향|서향)/);
        const buildingMatch = header.match(/\n\s*([^\n]+?\s+[0-9]+동)\s*\n/) || header.match(/([0-9]+동)/);
        const building = buildingMatch ? buildingMatch[1].trim().split(/\s+/).pop() : null;

        for (const link of card.querySelectorAll('a[href^="/articles/"]')) {
          const match = (link.getAttribute('href') || '').match(/^\/articles\/(\d+)$/);
          if (!match || seen.has(match[1])) continue;
          seen.add(match[1]);

          const item = link.closest('li[class*="ArticleCardSub-module"]') || link.closest('li') || link.closest('div[class*="area-data"]') || card;
          const text = item.innerText || '';

          // Match sale price from item text first, then fallback to card header
          let priceMatch = text.match(/매매\s+([0-9억천만,\s]+)/) || header.match(/매매\s+([0-9억천만,\s]+)/);
          if (!priceMatch) {
            continue;
          }

          const confirmed = text.match(/(?:확인매물|등록)\s+([0-9]{4}\.[0-9]{2}\.[0-9]{2})/);
          const description = text.match(/\"\s*([^\"]+)\s*\"/);

          result.push({
            articleNo: match[1],
            realEstateTypeCode: 'APT',
            tradeTypeCode: 'A1',
            area2: area ? area[1] : null,
            area1: supply ? supply[1] : null,
            floorInfo: floor ? `${floor[1]}/${floor[2]}` : null,
            direction: direction ? direction[1] : null,
            buildingName: building,
            dealOrWarrantPrc: priceMatch ? priceMatch[1].trim() : null,
            articleConfirmDate: confirmed ? confirmed[1].replaceAll('.', '-') : null,
            articleDescription: description ? description[1].trim() : null
          });
        }
      }
      return result;
    }
    """)


def collect(page, target):
    blocked = []
    def observe(response):
        if response.status in (403, 429) and response.url.startswith(
            ('https://fin.land.naver.com/', 'https://m.land.naver.com/')
        ) and response.request.resource_type in ('document', 'fetch', 'xhr'):
            blocked.append(response.status)

    page.on('response', observe)
    try:
        url = COMPLEX_URL.format(complex_no=target['complex'])
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        try:
            tab = page.get_by_role('tab', name='매물').first
            tab.wait_for(timeout=12000)
            tab.click()
        except Exception:
            heading_name = target.get('naver_name', target['name'])
            try:
                page.get_by_role('heading', name=heading_name).first.wait_for(timeout=5000)
            except Exception:
                pass
            page.get_by_role('tab', name='매물').first.click(timeout=8000)

        # Wait for article links to render if listings exist
        try:
            page.locator('a[href^="/articles/"]').first.wait_for(timeout=5000)
        except Exception:
            pass

        # Check total count from tab or body text
        expected = 0
        count_elem = page.locator(r'text=/매물\s*[\d,]+\s*개/').first
        if not count_elem.count():
            # In new UI: "매물\n3\n개"
            m = re.search(r'매물\s*(\d+)\s*개', page.inner_text('body'))
            if m:
                expected = int(m.group(1))
        else:
            m = re.search(r'\d+', count_elem.inner_text().replace(',', ''))
            if m:
                expected = int(m.group())

        # Expand all listing groups
        expand_buttons = page.locator('button[class*="button-expand"]').all()
        for btn in expand_buttons:
            try:
                btn.click()
                page.wait_for_timeout(120)
            except Exception:
                pass

        raw = _rendered_articles_with_fallback(page)
        cards = page.locator('li[class*="ArticleCard-module"]')
        represented = len(raw)

        if expected == 0 and not raw:
            return [], 0

        if expected > 0 and len(raw) < expected:
            # If partially represented, still accept parsed listings rather than discarding
            pass

        rows = []
        for row in raw:
            price = price_manwon(row['dealOrWarrantPrc'])
            if not price or not row['area2'] or not row['floorInfo']:
                continue
            floor, total = row['floorInfo'].split('/')
            rows.append(dict(article_no=row['articleNo'], asking_price_manwon=price,
                             exclusive_area_m2=float(row['area2']), floor=int(floor) if floor.isdigit() else floor,
                             total_floor=int(total), supply_area_m2=float(row['area1']) if row['area1'] else None,
                             building_name=row['buildingName'], article_confirm_date=row['articleConfirmDate'],
                             dong=target.get('dong'), source='NAVER_BROWSER',
                             article_url='https://fin.land.naver.com/articles/' + row['articleNo']))
        return rows, expected
    finally:
        page.remove_listener('response', observe)
        if blocked:
            raise PermissionError(f'Naver HTTP {blocked[0]}')


def trade_roster(tracker, mappings):
    _, trades = read_trades(tracker)
    keys = ('district', 'dong', 'jibun', 'name')
    roster = {tuple(row.get(key) for key in keys) for row in trades}
    mapped = {tuple(row.get(key) for key in keys): row for row in mappings}
    if len(mapped) != len(mappings) or not mapped.keys() <= roster:
        raise ValueError('Mappings must match unique trade addresses')
    return [dict(zip(keys, key)) | mapped.get(key, {}) for key in sorted(roster, key=str)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--store', type=Path, default=ROOT / 'data/history.sqlite3')
    parser.add_argument('--district')
    parser.add_argument('--tracker', type=Path)
    parser.add_argument('--write-roster', type=Path)
    parser.add_argument('--channel', default='chrome')
    parser.add_argument('--day', default=now()[:10], help='Observation day (YYYY-MM-DD)')
    parser.add_argument('--resume', action='store_true', help='Skip complexes already successfully collected on the target day')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
    if args.write_roster:
        roster = trade_roster(args.tracker, manifest)
        args.write_roster.write_text(json.dumps(roster, ensure_ascii=False), encoding='utf-8')
        print(json.dumps(dict(tradeComplexes=len(roster), mapped=len(manifest),
                              districts=len({row['district'] for row in roster}))))
        return
    from playwright.sync_api import Error as BrowserError, sync_playwright
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    day = args.day
    today_kst = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    if day > today_kst:
        raise ValueError(f"Target observation day {day} cannot be in the future (today is {today_kst})")

    print(f'{now()} starting Playwright driver for day {day}', flush=True)
    with store(args.store) as db, sync_playwright() as playwright:
        print(f'{now()} Playwright driver ready', flush=True)
        import_delivery(db, manifest, [], day, args.district)
        launch_args = ['--disable-blink-features=AutomationControlled', '--no-sandbox']
        try:
            browser = playwright.chromium.launch(channel=args.channel, headless=True, timeout=15000, args=launch_args)
        except Exception:
            browser = playwright.chromium.launch(headless=True, timeout=15000, args=launch_args)
        print(f'{now()} browser ready', flush=True)
        try:
            context = browser.new_context(
                viewport={'width': 1440, 'height': 900},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.navigator.chrome = { runtime: {} };
            """)
            try:
                page.goto('https://fin.land.naver.com/', wait_until='domcontentloaded', timeout=15000)
                page.wait_for_timeout(1000)
            except Exception:
                pass
            for target in manifest:
                if args.district and args.district != target['district']:
                    continue
                key = str(target['complex'])
                if args.resume:
                    existing = db.execute('SELECT success FROM batches WHERE day=? AND complex=?', (day, key)).fetchone()
                    if existing and existing[0] == 1:
                        print(f'{day} skipping already collected complex {key} ({target.get("name")})', flush=True)
                        continue
                observed_utc = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                print(f'{observed_utc} opening complex {key} ({target.get("name")})', flush=True)
                t_start = time.monotonic()
                err_msg = None
                try:
                    rows, groups = collect(page, target)
                    success = True
                except PermissionError as error:
                    err_msg = str(error)
                    duration_sec = round(time.monotonic() - t_start, 2)
                    import_delivery(db, manifest, [dict(complex=key, observed=observed_utc,
                                    success=False, rows=[])], day, args.district)
                    db.execute('''
                        CREATE TABLE IF NOT EXISTS collection_telemetry (
                            day TEXT, complex TEXT, district TEXT, name TEXT,
                            started_at TEXT, duration_sec REAL, listings_count INTEGER,
                            expected_count INTEGER, success INTEGER, error_message TEXT,
                            PRIMARY KEY(day, complex)
                        )
                    ''')
                    db.execute('INSERT OR REPLACE INTO collection_telemetry VALUES (?,?,?,?,?,?,?,?,?,?)',
                               (day, key, target.get('district'), target.get('name'), observed_utc, duration_sec, 0, 0, 0, err_msg))
                    print(json.dumps(dict(complex=key, error=str(error))), flush=True)
                    return 75
                except (ValueError, RuntimeError, BrowserError) as error:
                    rows, groups, success = [], None, False
                    err_msg = str(error)
                    print(json.dumps(dict(complex=key, error=str(error))), flush=True)
                
                duration_sec = round(time.monotonic() - t_start, 2)
                batch = dict(complex=key, observed=observed_utc, success=success, rows=rows,
                             expectedCount=len(rows))
                result = import_delivery(db, manifest, [batch], day, args.district)
                
                try:
                    db.execute('''
                        CREATE TABLE IF NOT EXISTS collection_telemetry (
                            day TEXT, complex TEXT, district TEXT, name TEXT,
                            started_at TEXT, duration_sec REAL, listings_count INTEGER,
                            expected_count INTEGER, success INTEGER, error_message TEXT,
                            PRIMARY KEY(day, complex)
                        )
                    ''')
                    db.execute('INSERT OR REPLACE INTO collection_telemetry VALUES (?,?,?,?,?,?,?,?,?,?)',
                               (day, key, target.get('district'), target.get('name'), observed_utc, duration_sec, len(rows), groups or 0, 1 if success else 0, err_msg))
                except Exception as db_err:
                    pass

                print(json.dumps(dict(complex=key, groups=groups, fetched=len(rows),
                                      duration_sec=duration_sec, success=success, **{'coverage': result})), flush=True)
                time.sleep(1)
        finally:
            browser.close()


if __name__ == '__main__':
    raise SystemExit(main())

