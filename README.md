# APT WATCH

서울 아파트 신고가 트래커의 SQLite를 읽기 전용으로 연결하는 별도 서비스다. 기존 트래커에 변경을 가하지 않는다.

## 실행

APT WATCH 폴더에서 Python 3.12로 실행한다. Windows에 IANA 시간대 데이터가 없으면 기존 트래커와 같이 tzdata가 필요하다.

    python apt_watch.py
    python -m http.server 4175 --bind 127.0.0.1 --directory site

http://127.0.0.1:4175/ 에서 본다. 갱신된 원자료로 첫 명령을 다시 실행하면 site/data.json이 바뀐다. 생성된 공개 파일은 집계만 담는다.

## 기존 자산 조사

- seoul-apartment-tracker/data/tracker.sqlite3에 2019년 이후 서울 25개 구 자료가 있다. 기존 API 연동 및 자동 갱신은 트래커가 담당한다. APT WATCH는 트래커의 최신 스냅샷을 읽는다. 행별 최초 공개일은 현재 거래 테이블만으로 복원할 수 없다.
- pyungchon_land/collectors/naver_land.py는 안양시 동안구, 대상 법정동 및 최소 면적 필터에 묶여 있다. 매물 ID·가격 단위 검사·페이지 완결성 확인 코드는 재사용 후보이며 기존 코드에는 HTTP 403/429 기록이 있다. 서울 25개 구 정상 수집은 검증되지 않았다. 네이버 허용 경로가 확인되면 기존 수집기의 출력과 아래 형식을 연결한다.
- 기존 트래커 배포는 로컬 Python과 GitHub Pages 게시 스크립트에 기반한다. 새 프로젝트는 집계 파일만 Pages로 보내는 별도 워크플로를 제공한다.

## 호가 관측 이력

네이버 화면 수집은 기존 평촌 Playwright 환경과 Chrome을 사용한다.
APT WATCH 폴더에서 아래 명령으로 확인된 매핑만 실행한다.

    ..\.venv-land\Scripts\python.exe collect_naver.py --manifest data/naver-mappings.json --district 11470

매핑 항목은 `complex`(네이버 ID), `district`, `dong`, `jibun`, `name`(실거래 단지명),
`naver_name`(네이버 화면 단지명)이다. 실거래에서 확인한 단지 후보 전체는 다음과 같이 생성한다.

    ..\.venv-land\Scripts\python.exe collect_naver.py --manifest data/naver-mappings.json --tracker ../seoul-apartment-tracker/data/tracker.sqlite3 --write-roster data/seoul-trade-roster.json

단지 후보 명부의 미매핑 행은 수집 대상 명부에 넣기 전에 주소와 네이버 ID를 확인한다.
화면의 매물 묶음 수와 개별 ID 수를 각각 기록한다. 화면에서 목록 완결성이 확인되지
않은 관측은 실패로 남긴다. 호가 관측 후 `apt_watch.py`를 실행하면 대시보드의 집계가 갱신된다.

허용된 공급 경로에서 정규화한 JSONL을 python apt_watch.py --import-feed 경로 로 적재한다. 각 줄의 필수 키는 observed(오프셋 포함 ISO 시각), complex(공급자 내 고유 단지 ID), success(완전한 관측 성공 여부), rows(매물 배열)다. 매물 필수 키는 article_no, asking_price_manwon이다. 원본 공급 필드를 행에 포함해 보존할 수 있다. 성공 배치와 매물 관측은 단지·한국 날짜 단위로 중복 삽입되지 않는다. 실패 이후 같은 날 성공 배치는 적재 가능하다. 성공 빈 배열은 완전한 검색 결과를 받은 경우에만 사용한다.

python apt_watch.py --events 로 관측 이력에서 이벤트를 재현한다. 연속 성공 관측 사이에서 ID가 유지된 매물의 가격 변화를 추적한다. 관측 중단과 재등장은 동일 ID 기준이다. 중개사 간 중복 및 ID 변경은 추가 식별 근거가 필요하다. 7일·30일 인상·인하 비중은 기간 전체를 연속 관측한 단지의 동일 ID 표본에서 계산한다. 서울 전역 커버리지를 주장하려면 별도의 전체 단지 목록이 필요하다.

## 가격지수

2019년 1월 100. 구·법정동·지번·단지명·전용면적 내림·층 구간(3층 이하, 4~9층, 10층 이상)으로 묶는다. 각 그룹의 월 중위 가격을 구해 공통 그룹 10개 이상의 로그 가격비 중위값을 직전 산출 월에 연결한다. 최대 12개월까지 관측 월을 건너뛸 수 있으며 누락 월은 빈 값이다. 거래가 적은 구는 별도로 미산출된다. 같은 그룹 안의 층 차이와 거래 구성 변화는 남아 있다. 최근 30일과 겹치는 월은 잠정이며, 스냅샷 개정 시 재계산한다. 집계 산식 버전과 생성 결과는 별도 SQLite에 보존한다.

## 클라우드 운영

별도 GitHub 저장소 루트에 이 프로젝트를 두고 Pages 소스를 GitHub Actions로 설정한다. 비공개 S3 호환 버킷에 허가된 공급자가 최신 listings.jsonl을 놓고, 실거래 수집 작업이 일관된 SQLite 백업 tracker.sqlite3를 공급해야 한다. 처음에는 프로그램이 초기화한 history.sqlite3를 버킷에 올린다. 버킷과 엔드포인트는 APT_WATCH_BUCKET, APT_WATCH_STORAGE_ENDPOINT 변수, 자격증명은 APT_WATCH_STORAGE_KEY, APT_WATCH_STORAGE_SECRET Secrets로 지정한다. 워크플로 기본 실행은 06:00 KST이며 schedule을 수정하면 변경된다. 동일 저장소 실행을 직렬화한다. 상태 DB와 원자료는 버킷에, site 폴더만 Pages에 게시한다. 원천 입력 두 종류의 공급과 저장소 설정은 현재 연결되지 않았다.

## 검증 범위

python -m unittest discover -s tests -v 로 재실행 중복 방지, 실패 처리, 인하·재등장, 해제 제외, 비교 표본 부족 구간 처리를 확인한다. 실제 서울 데이터로 지수 생성 완료. 호가지수·괴리율·종합 심리·선행성·한국부동산원 비교, 외부 배포와 운영 실측은 후속 작업이다. 네이버 자동 수집 허용 여부는 https://policy.naver.com/policy/disclaimer.html 참조.

2차 검증의 결과와 승인된 서울 호가 명부·파일 입력 방식은 [2차 검증 보고서](AUDIT_2.md)를 참고한다. 클라우드 작업에는 complexes.json도 필요하다. 단지 명부는 complex, district, name 키가 있는 객체 배열이다. 일일 JSONL의 성공 배치에는 expectedCount가 필요하다.

3차 산식·협상 지표 정의와 재현 방법은 [3차 검증 및 운영](VALIDATION_3.md)을 참고한다. 현재 기본 실거래지수는 월·그룹 고정효과이며 기존 연쇄지수는 연구용 선택지에 보존되어 있다.
