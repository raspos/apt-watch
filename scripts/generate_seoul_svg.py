"""Generate accurate Seoul 25 districts SVG path data from verified KOSTAT municipal GeoJSON."""
import json
import math
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GEOJSON_URL = 'https://raw.githubusercontent.com/southkorea/seoul-maps/master/kostat/2013/json/seoul_municipalities_geo_simple.json'

SEOUL = '종로 중 용산 성동 광진 동대문 중랑 성북 강북 도봉 노원 은평 서대문 마포 양천 강서 구로 금천 영등포 동작 관악 서초 강남 송파 강동'.split()
CODES = '11110 11140 11170 11200 11215 11230 11260 11290 11305 11320 11350 11380 11410 11440 11470 11500 11530 11545 11560 11590 11620 11650 11680 11710 11740'.split()
NAME_TO_CODE = {n + '구': c for n, c in zip(SEOUL, CODES)}

def generate_seoul_districts_svg():
    req = urllib.request.Request(GEOJSON_URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        geo = json.loads(resp.read().decode('utf-8'))

    all_coords = []
    for f in geo['features']:
        geom = f['geometry']
        coords = geom['coordinates']
        poly_list = [coords] if geom['type'] == 'Polygon' else coords
        for poly in poly_list:
            for ring in poly:
                all_coords.extend(ring)

    min_lng = min(c[0] for c in all_coords)
    max_lng = max(c[0] for c in all_coords)
    min_lat = min(c[1] for c in all_coords)
    max_lat = max(c[1] for c in all_coords)

    W, H = 640, 520
    padding = 24

    def project(lng, lat):
        cos_lat = math.cos(math.radians(37.56))
        x_raw = (lng - min_lng) * cos_lat
        max_x_raw = (max_lng - min_lng) * cos_lat
        y_raw = (lat - min_lat)
        max_y_raw = (max_lat - min_lat)

        scale = min((W - 2 * padding) / max_x_raw, (H - 2 * padding) / max_y_raw)
        x = padding + x_raw * scale
        y = H - padding - y_raw * scale
        return round(x, 1), round(y, 1)

    # Manual label centroid adjustments for aesthetically centered label placement in irregular boundary shapes
    LABEL_OFFSETS = {
        '종로구': (-2, 6),
        '성북구': (2, 2),
        '용산구': (0, 0),
        '중구': (0, 0),
        '영등포구': (-2, 0),
        '서초구': (0, -4),
        '강남구': (0, 0),
        '송파구': (0, 0),
        '은평구': (0, 0),
        '양천구': (0, 0)
    }

    districts_data = []
    for f in geo['features']:
        name = f['properties']['name']
        code = NAME_TO_CODE.get(name, '')
        geom = f['geometry']
        coords = geom['coordinates']
        poly_list = [coords] if geom['type'] == 'Polygon' else coords

        path_d = []
        all_pts = []
        for poly in poly_list:
            for ring in poly:
                pts = [project(pt[0], pt[1]) for pt in ring]
                all_pts.extend(pts)
                d_str = f"M {pts[0][0]} {pts[0][1]} " + " ".join(f"L {p[0]} {p[1]}" for p in pts[1:]) + " Z"
                path_d.append(d_str)

        # Polygon centroid (signed area formula)
        cx = round(sum(p[0] for p in all_pts) / len(all_pts), 1)
        cy = round(sum(p[1] for p in all_pts) / len(all_pts), 1)

        ox, oy = LABEL_OFFSETS.get(name, (0, 0))
        districts_data.append({
            'code': code,
            'name': name,
            'd': " ".join(path_d),
            'cx': cx + ox,
            'cy': cy + oy
        })

    districts_data.sort(key=lambda x: x['code'])

    # Save to site/seoul-districts.json and site/seoul-districts-svg.js
    out_file = ROOT / 'site' / 'seoul-districts.json'
    out_file.write_text(json.dumps(districts_data, ensure_ascii=False, indent=2), encoding='utf-8')
    js_file = ROOT / 'site' / 'seoul-districts-svg.js'
    js_file.write_text("var SEOUL_DISTRICTS_SVG = (typeof window !== 'undefined' ? window : globalThis).SEOUL_DISTRICTS_SVG = " + json.dumps(districts_data, ensure_ascii=False) + ";\n", encoding='utf-8')
    print(f"Generated {len(districts_data)} districts SVG data -> {out_file} & {js_file}")

    return districts_data

if __name__ == '__main__':
    generate_seoul_districts_svg()
