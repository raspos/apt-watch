# [학술 연구 제안서] 호가-실거래가 네고율(List-to-Sale Price Discount)의 시계열 동학과 주택시장 선행성에 관한 실증 연구

**Research Proposal:** Empirical Dynamics of the Asking-to-Contract Price Discount and Its Leading Information for Housing Market Trajectories: The APT WATCH Initiative

**제출처:** 부동산경제학 / 부동산학 전공 심사 및 자문 교수회  
**연구 수행:** APT WATCH 데이터저널리즘 랩 & 부동산계량연구팀  
**문서 버전:** Version 1.1 (2026. 11. 13 개정)  

---

## 1. 연구의 출발점과 문제의식

### 1-1. 배경: 가격 형성의 비대칭성과 사후적 통계의 정보 시차
주택시장은 전형적인 탐색 및 매칭(Search and Matching) 시장으로, 이질적인(Heterogeneous) 재화와 정보 비대칭성 속에서 거래가 체결됩니다. 거래 성사 이전의 시장 상태는 매도자가 제시하는 **호가(Asking Price)**와 매수자의 **지불용의(Willingness to Pay)** 사이의 끊임없는 탐색과 교섭(Bargaining) 과정으로 규정됩니다.

현재 한국 주택시장의 표준 지표로 활용되는 공공 및 민간 통계는 다음과 같은 구조적 특성과 시차를 수반합니다:
1. **한국부동산원(REB) 주간 아파트 가격동향:** 전문 조사원이 현장 조사 및 협조 공인중개사 네트워크를 통해 거래가능가격을 산정하고 실거래가를 상시 모니터링하여 검증하는 공인 통계이나, 거래 빈도가 급감하는 침체기나 시장 급변기에는 보수적 가격 산정과 주간 정기 조사 주기로 인해 급격한 가격 양보(Concession)를 실시간 반영하는 데 시차가 발생할 수 있습니다.
2. **국토교통부 실거래가 기반 지수:** 법정 실거래 신고 기한(계약일로부터 30일 이내)과 실제 지자체 실등록 시차(평균 10~18일)로 인해 공표 시점에 실질적인 정보 시차가 존재하며, 거래가 활발한 특정 단지나 평형 위주로만 지수가 가중되는 **거래 선택 편향(Trading Volume Selection Bias)**을 내포합니다.
3. **매매수급동향 / 매수우위지수:** 설문조사 기반의 정성적 심리지수로, 시장 참여자의 심리 방향성은 파악할 수 있으나 매도자가 계약 테이블에서 양보하는 **금액적·정량적 할인 폭(% 또는 %p)**을 수치화하지 못합니다.

### 1-2. 핵심 아이디어 및 연구 목적
APT WATCH는 **"매도자의 요구가격(호가)과 실제 체결가격(실거래가) 사이에서 관측되는 가격 차이(Observed Price Gap), 즉 네고율(Nego Discount)의 등락이 주택시장의 가장 빠르고 정밀한 선행 신호(Leading Indicator)로 기능할 수 있는가?"**라는 질문을 탐구합니다.

호가는 매도자의 가격 기대치를 반영하고, 실거래가는 매수자와의 최종 합의점을 나타냅니다. 매도자 호가 대비 실거래가의 할인 폭(네고율)의 변화는 이론적으로 시장 교섭력(Bargaining Power)의 상대적 이동을 반영하는 대리 지표 후보로 해석될 수 있습니다. 다만 이는 매도자의 유동성 압박, 주택의 미관측 질적 특성, 거시 금융 여건의 복합적 영향을 받으므로, 본 연구는 이를 단정적 인과로 규정하지 않고 **검증 가능한 실증 가설(Testable Hypotheses)**로 다룹니다.

본 연구의 최종 목적은 특정 시점의 절대 네고율 수준보다, **시간에 따른 네고 폭의 변화($\Delta \text{Nego}$)**가 기존 부동산 지표 대비 미래 주택가격 및 거래량의 변곡점을 선행 설명하는 추가적 정보가치(Incremental Information Value)를 지니는지 계량경제학적으로 검증하는 것입니다.

---

## 2. 이론적 배경 및 국내외 선행연구 검토

### 2-1. 해외 선행연구: List-to-Sale Price Ratio와 시장 유동성
해외 부동산경제학계에서는 매물 호가 대비 실거래가 비율(Sale-to-List Price Ratio 또는 List-to-Sale Discount)에 대한 미시적 실증 연구가 활발히 진행되어 왔습니다:
- **Genesove & Mayer (2001, QJE):** 손실회피(Loss Aversion) 성향을 가진 매도자가 시장 하락기에도 호가를 낮추지 않고 버티며, 그 결과 호가와 실제 매매가격의 괴리가 커지고 매물 체류기간(Time on Market, TOM)이 급증함을 보스턴 주택시장을 대상으로 실증했습니다.
- **Merlo & Ortalo-Magné (2004, The Economic Journal):** 잉글랜드 주택시장의 미시 매물 추적 데이터를 활용하여 매도자의 공표 호가 인하(Price Revision)와 최종 계약 테이블에서의 교섭(Bargaining Discount)을 분리하여 모형화하였으며, 최초 호가와 최종 확인 호가의 차이를 엄밀히 구분해야 함을 규명했습니다.
- **Anenberg & Laufer (2017, JUE):** 대규모 온라인 포털의 일별 매물 데이터(Listings)와 거래 데이터를 결합하여, 실거래 지수가 공식 집계되기 수개월 전에 호가 조정 및 호가 대비 계약 할인율을 통해 시장의 터닝포인트를 조기 예측할 수 있는 Listing Price Index를 개발했습니다.

### 2-2. 국내 선행연구와 본 연구의 차별성
- **최성호 (2018, 주택연구):** 서울·수도권 아파트 시장을 대상으로 패널 벡터자기회귀모형(Panel VAR)을 적용하여 매도호가와 실거래가의 동태적 관계를 분석하였으며, 매도호가가 실거래가에 미치는 선행적 영향력이 더 강함을 확인했습니다.

**본 연구의 차별성:**  
기존 국내 연구는 월간 또는 분기 단위의 집계 자료나 단편적 표본에 주로 의존했습니다. 반면 APT WATCH는 **서울 25개 자치구 5,821개 매핑 풀 중 일일 연속 관측을 수행하는 110~375개 핵심 표본 단지의 일별 미시 패널(Daily Micro Panel)**을 직접 구축하고, 국토교통부 실거래 전수 자료와 결합하여 계약일 이전 관측 이력을 정밀 대조하는 체계를 갖추었다는 점에서 데이터의 적시성과 미시적 분해능에서 뚜렷한 학술적 차별성을 지닙니다.

---

## 3. 핵심 변수 정의 및 가설 체계 (Hypotheses)

### 3-1. 3대 가격의 엄격한 정의
시점이 서로 다른 가격을 혼동하지 않기 위해 다음과 같이 엄밀하게 조작적으로 정의합니다:
1. **최초 관측 호가 ($P_{\text{ask}, 0}$):** 수집 시스템 크롤러가 포털에서 해당 매물을 처음 탐지한 시점의 매도 희망가격 (포털 실제 최초 등록일과 수집 주기 사이의 시차가 존재할 수 있음).
2. **최종 확인 호가 ($P_{\text{ask}, \text{last}}$):** 계약일 직전까지 포털에서 마지막으로 정상 확인된 매도 호가 (계약 당일 매도자-매수인 간 구두로 최종 합의된 오프라인 호가와는 차이가 있을 수 있음).
3. **실제 계약가격 ($P_{\text{contract}}$):** 계약서에 명시되어 국토교통부에 법정 신고된 실거래가격.

### 3-2. 할인율 산식
- **최종 호가 대비 네고율 (Closing Nego Discount):**
  $$\text{Nego}_{it} = \frac{P_{i, t}^{\text{last\_ask}} - P_{i, t}^{\text{contract}}}{P_{i, t}^{\text{last\_ask}}} \times 100 \quad (\%)$$
  *(단, $t_{\text{first}} \le t_{\text{contract}}$인 시간적 선행 관측 매물에 한해, 계약일 이전 마지막 호가 $P_{\text{last\_before}}$만을 분모로 사용)*
- **주간/월간 네고 폭 변화 (%p):**
  $$\Delta \text{Nego}_{t} = \text{Nego}_{t} - \text{Nego}_{t-k} \quad (\%p)$$

### 3-3. 검증할 5대 연구 가설
- **[H1. 가격 선행성]** 네고율의 확대($\Delta \text{Nego} > 0$)는 향후($t+4\text{주} \sim t+12\text{주}$) 주택 실거래가격 상승률의 둔화 또는 하락 전환을 통계적으로 유의미하게 선행할 것이다.
- **[H2. 반등 선행성]** 네고율의 축소($\Delta \text{Nego} < 0$)는 향후 실거래가격의 반등 또는 상승세 강화를 선행할 것이다.
- **[H3. 거래량과의 비선형 관계]** 네고 폭 확대 초기에는 거래량이 감소(매수자 관망)하다가, 매도자의 투매성 가격 양보로 네고율이 임계치를 초과할 때 거래량이 일시 반등하는 비선형적(Non-linear) 관계를 보일 것이다.
- **[H4. 가격괴리지수(호가 프리미엄)의 매개 효과]** 집단적 가격괴리지수(C등급)의 확대는 호가 인하 비중 증가를 유발하고, 이는 최종적으로 개별 거래의 네고율(A/B등급) 확대로 전이될 것이다.
- **[H5. 기존 통계 대비 추가 정보가치]** 한국부동산원 및 KB부동산 지수로 구성된 기준 예측 모형에 '네고율 변화폭' 변수를 추가할 경우, 외표본(Out-of-sample) 예측 오차(RMSE, MAE)가 통계적으로 유의미하게 감소할 것이다.

---

## 4. 데이터 구축 및 매물-실거래 연계 3단계 검증 체계

공개 포털 매물과 국토교통부 실거래 자료는 개인정보 보호 원칙상 고유 동·호수가 비식별 처리되어 있습니다. 본 연구는 인위적 단정을 방지하기 위해 매칭 신뢰도를 3단계로 엄격히 분리합니다:

| 등급 | 명칭 | 매칭 요건 및 시간적 인과성 원칙 | 연구 활용 및 공표 정책 |
| :---: | :---: | :--- | :--- |
| **Grade A** | **확인된 동일 주택 거래** | 공인중개사 거래 확약, 계약서 사본 등 독립 증빙 1:1 일치 | **공식 확정 네고지수 산출 및 대외 공표** |
| **Grade B** | **확률적 단일후보 매칭** | 동일 단지·지번·면적($\pm 0.5m^2$)·층수 일치, **$t_{\text{first}} \le t_{\text{contract}}$ 필수**, 유일 후보(1:1) | **내부 학술 연구 및 민감도 분석 전용 (대외 비공표)** |
| **Grade C** | **코호트 가격괴리 지표** | 동일 스트라텀(단지·면적·층구간) 전체 활성 호가와 최근 실거래 기준가격 비교 | **가격괴리지수(Price Divergence)**로 독립 운영 |

> [!IMPORTANT]
> **시간적 인과성 원칙 (Temporal Causality Rule):**
> 계약일 이후에 처음 관측된 매물($t_{\text{first}} > t_{\text{contract}}$)은 역순 관측(Reverse-temporal match)으로 규정하여 B등급 표본에서 원천 배제합니다. 유효 표본이 0건인 초기 구간에서는 네고율을 임의 산출하지 않고 '산출 유보'로 관리합니다.

---

## 5. 실증 계량경제학 모형 설계 (Econometric Specifications)

### 5-1. 정보가치 검증 모형 (Incremental Information Value Test)
기존 주택가격 예측 모형(Baseline Model)과 네고지수를 포함한 확장 모형(Augmented Model)을 비교합니다:

#### [모형 1: 기존 통계 기준 모형 (Baseline Model)]
$$\Delta \ln(P_{k, t+h}) = \alpha_0 + \sum_{j=1}^p \beta_j \Delta \ln(P_{k, t-j}) + \sum_{j=0}^q \gamma_j \Delta \text{REB}_{k, t-j} + \sum_{j=0}^q \theta_j \Delta \text{KB}_{k, t-j} + \sum_{j=0}^q \phi_j \ln(\text{Vol}_{k, t-j}) + \mu_k + \epsilon_{kt}$$

#### [모형 2: APT WATCH 네고 확장 모형 (Augmented Model)]
$$\Delta \ln(P_{k, t+h}) = [\text{Baseline Model}] + \sum_{j=0}^r \lambda_j \text{Nego}_{k, t-j} + \sum_{j=0}^r \psi_j \Delta \text{Nego}_{k, t-j} + \sum_{j=0}^r \omega_j \text{Spread}_{k, t-j}^{\text{Grade C}} + \eta_{kt}$$

- $k$: 서울시 25개 자치구
- $h$: 예측 시계 (4주, 8주, 12주)
- $\text{Spread}_{k, t}^{\text{Grade C}}$: 가격괴리지수 (Proxy)

### 5-2. 외표본 예측력 평가 (Out-of-sample Forecasting Evaluation)
- **롤링 윈도우(Rolling Window) 추정:** 미래 정보의 사전 누출(Look-ahead Bias)을 차단하기 위해 30일 신고 시차를 반영하여 과거 시점 가용 정보만으로 순차 추정합니다.
- **예측력 비교 통계량:** Diebold-Mariano(1995) 검정을 통해 두 모형 간 평균제곱오차(MSE)의 차이가 통계적으로 유의한지 검증합니다:
  $$\text{DM-Statistic} = \frac{\bar{d}}{\sqrt{\hat{V}(\bar{d})}} \sim N(0, 1)$$

---

## 6. 교수 자문 요청 5대 핵심 쟁점 (Discussion Points)

1. **[식별 문제] B등급 추정 매칭의 계량적 타당성:**
   - A등급 표본이 제한적인 초기 환경에서, B등급(단일 후보 매칭) 자료를 활용할 때 발생할 수 있는 매칭 오차(Measurement Error in Matching)를 도구변수(IV) 또는 헤크만 2단계 모형(Heckman Selection)으로 보정할 수 있는 최적 방안은 무엇인가?
2. **[표본 선택 편향] 거래 성사 매물의 내생성(Endogeneity):**
   - 네고율은 '실제로 거래된 주택'에서만 관측되므로, 시장에서 끝내 팔리지 않은 장기 미체결 매물(Unsold Inventory)의 협상 실패가 과소 반영되는 편향을 생존 분석(Hazard Model)으로 어떻게 결합 통제해야 하는가?
3. **[공간적 전이] 자치구 간 네고 압력의 공간 계량 모형(Spatial Econometrics):**
   - 강남 3구 또는 마용성 등 선도 지역의 네고율 변화가 서울 외곽 자치구로 확산되는 시차 구조를 공간 자기회귀 모형(Spatial Lag / SAR / SEM)으로 분석하는 것이 학술적으로 적절한가?
4. **[대리 지표와의 연결] 가격괴리지수와 네고율의 통계적 결합:**
   - 호가 프리미엄(C등급 가격괴리)과 실제 협상 할인율(A등급 네고율)의 상호작용 항을 구성할 때 다중공선성(Multicollinearity)을 회피하기 위한 주성분(PCA) 또는 오차수정모형(VECM)의 적합성은 어떠한가?
5. **[학술지 투고 전략]:**
   - 본 연구의 데이터셋과 분석 틀이 「국토계획」, 「부동산학연구」, 「주택연구」 또는 SSCI급 국제학술지(Journal of Housing Economics, Real Estate Economics)에 게재되기 위해 추가로 보완해야 할 필수 방법론적 요건은 무엇인가?

---

## 7. 학술 참고문헌 (References)

- Anenberg, E., & Laufer, S. (2017). A more timely measure of housing market activity: The listing price index. *Journal of Urban Economics*, 98, 1-13. https://doi.org/10.1016/j.jue.2016.12.002
- Case, K. E., & Shiller, R. J. (1989). The efficiency of the market for single-family homes. *The American Economic Review*, 79(1), 125-137.
- Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253-263. https://doi.org/10.1080/07350015.1995.10524599
- Genesove, D., & Mayer, C. (2001). Loss aversion and seller behavior: Evidence from the housing market. *The Quarterly Journal of Economics*, 116(4), 1233-1260. https://doi.org/10.1162/003355301753265561
- Merlo, A., & Ortalo-Magné, F. (2004). Bargaining over residential real estate: evidence from England. *The Economic Journal*, 114(495), 360-384. https://doi.org/10.1111/j.1468-0297.2004.00209.x
- 최성호 (2018). 아파트 매도호가와 실거래가의 관계 분석 (서울 수도권 아파트 시장을 중심으로). *주택연구*, 26(1), 89-106. https://doi.org/10.24957/hsr.2018.26.1.89
