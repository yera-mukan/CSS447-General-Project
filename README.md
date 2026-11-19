# OCR Autoscaling Lab — k3s на одном узле AWS EC2

Исследовательский стенд для сравнения стратегий автомасштабирования OCR-сервиса
(`ferraripupu/ocr-app`) под спайковой нагрузкой. Всё развёрнуто на **одном узле
k3s** в AWS, нагрузка генерируется k6, метрики собираются Prometheus, визуализация —
Grafana. Результаты, сырые данные и русскоязычные объяснения лежат в репозитории.

> Главный вывод: на узле с 2 vCPU **автомасштабирование реплик не увеличивает
> пропускную способность** — работа упирается в CPU. HPA корректно масштабирует
> поды, VPA корректно считает requests, но реальный выигрыш даёт только более
> крупный узел или несколько узлов. Подробности и цифры — ниже.

---

## 1. Краткие результаты

Профиль нагрузки: ~10 минут, пик 10 одновременных VU, один прогон на сценарий.

| Сценарий | p95 | Ошибки | RPS | Реплики avg/max | Pending | Рестарты | allocated $ | $/1k успешных |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `A-fixed` (3 реплики) | 39.8 с | 0% | 0.256 | 3.00 / 3 | 0 | 0 | 0.0102 | 0.0661 |
| `B-hpa-30` | **24.4 с** | 0% | 0.266 | 2.41 / 3 | 0 | 0 | 0.0082 | 0.0514 |
| `B-hpa-50` | 24.7 с | 0% | 0.264 | 2.46 / 3 | 0 | 0 | 0.0084 | 0.0528 |
| `B-hpa-70` | 24.5 с | 0% | 0.267 | 2.46 / 3 | 0 | 0 | 0.0084 | 0.0525 |
| `C-vpa-auto` | 31.2 с | 0% | 0.260 | 1.98 / 2 | 0 | 0 | 0.0067 | 0.0429 |
| `D-hpa-cpu-vpa-mem` | 41.0 с | 0% | 0.265 | 2.51 / 3 | 0 | 0 | 0.0086 | 0.0535 |
| `E-vpa-off` | 25.0 с | 0% | 0.263 | 1.00 / 1 | 0 | 0 | **0.0034** | **0.0213** |

`node_cost` у всех прогонов одинаковый — около **$0.0170** за 10 минут
(цена узла $0.10175/ч): число подов не меняет счёт за уже запущенный EC2.

- **Дешевле всего** — `E-vpa-off`: одна реплика, VPA только рекомендует.
- **Формально лучшая p95** — `B-hpa-30`, но отрыв от B-50/B-70 в пределах шума.
- **Хуже всего** — `A-fixed` и `D`: вероятно, из-за переподписки CPU
  (много процессов OCR на 2 ядрах) и шума одной повторности.
- **HPA работал**: во всех B и в D дошёл до 3 реплик, Pending не было.
- **VPA работал**: target `500m CPU / 256Mi RAM`; в C поды не вытеснялись,
  потому что requests 400m были внутри `[250m, 500m]`.

Полные данные: [`results/comparison.md`](results/comparison.md),
[`docs/07-results.md`](docs/07-results.md).

---

## 2. Цель и вопросы исследования

Сравнить пять стратегий автомасштабирования OCR-сервиса по:

- p95 латентности и проценту ошибок;
- числу реплик, requests/limits, реальному CPU/RAM;
- рестартам и Pending-подам;
- модельной стоимости зарезервированных ресурсов и за 1000 запросов.

Вопросы:

1. Даёт ли HPA выигрыш по латентности/пропускной способности на одном узле?
2. Насколько VPA-рекомендации отличаются от ручных requests?
3. Можно ли совмещать HPA и VPA, и как не получить конфликт?
4. Сколько «стоит» каждая стратегия, если считать зарезервированные ресурсы?
5. Где предел одноузлового стенда?

---

## 3. Стенд и версии

| Параметр | Значение |
|---|---|
| Инстанс | `m7i-flex.large`, 2 vCPU / 8 GiB, `$0.10175/ч` on-demand |
| allocatable | **cpu = 2**, **memory = 7961972Ki (~7.59 GiB)** |
| ОС | Ubuntu 26.04.1 LTS |
| Kubernetes | k3s `v1.37.2+k3s1` (Kubernetes 1.37.2) |
| Приложение | `ferraripupu/ocr-app@sha256:3e1fb257…b1b326` (digest закреплён) |
| VPA | `1.8.1` (официальный `kubernetes/autoscaler`) |
| Мониторинг | kube-prometheus-stack `93.4.1` |
| Prometheus | `v3.16.0`, retention 48h, scrape 15s |
| Grafana | `13.3.1` |
| kube-state-metrics | `v2.20.0` + customResourceState для VPA |
| k6 | `v2.4.0` |
| Helm | `v4.3.2` |
| Namespace | `ocr-lab` |

`c5.xlarge` (4 vCPU / 8 GiB) в аккаунте был недоступен, поэтому согласован
`m7i-flex.large`. Это ключевое ограничение: **на узле помещается максимум
3 пода OCR** при requests 400m (3×400m + 780m системных/мониторинга = 1980m).

Параметры собраны в [`env.sh`](env.sh); манифесты их не хардкодят.

---

## 4. Архитектура

```
                       одна EC2 (m7i-flex.large, 2 vCPU / 8 GiB)
 ┌──────────────────────────────────────────────────────────────────────┐
 │  Ubuntu 26.04 + k3s v1.37.2                                          │
 │                                                                      │
 │  namespace ocr-lab                    namespace monitoring           │
 │  ┌────────────────────────────┐       ┌───────────────────────────┐  │
 │  │ Deployment/ocr (1..3 pods) │       │ Prometheus (48h, 15s)     │  │
 │  │  container :8884           │◄──────│ kube-state-metrics        │  │
 │  │  tesseract pool max=2      │ scrape│ node-exporter             │  │
 │  │                            │       │ Grafana 13.3.1            │  │
 │  │ Service/ocr (ClusterIP)    │       │ Operator                  │  │
 │  │ Service/ocr-nodeport :30884│       └───────────────────────────┘  │
 │  └────────────▲───────────────┘                    ▲                  │
 │               │ NodePort (localhost)               │ remote write     │
 │  ┌────────────┴───────────────┐                    │                  │
 │  │ k6 на том же хосте          │────────────────────┘                  │
 │  │ spike.js, 1→10 VU, ~10 мин  │                                       │
 │  └────────────────────────────┘                                       │
 │                                                                      │
 │  VPA 1.8.1 в kube-system: recommender / updater / admission          │
 └──────────────────────────────────────────────────────────────────────┘
        ▲
        │ SSH-туннель или (в лаборатории) SG-правила на 13000/19090
   браузер: Grafana / Prometheus
```

Важные особенности:

- k6 и Prometheus работают **на том же узле**, что и приложение, и отбирают
  у него CPU. Это систематическая погрешность, учтённая в выводах.
- Grafana/Prometheus не публикуются через Ingress. В лаборатории доступ
  организован port-forward'ами на `0.0.0.0` (systemd) + SG.
- `Service/ocr-nodeport` (30884) используется только генератором нагрузки,
  чтобы port-forward не рвался при пересоздании подов.

---

## 5. Структура репозитория

```
.
├── README.md                  # этот обзор
├── AGENTS.md                  # исходное задание/план
├── env.sh                     # параметры узла, образа, версий
├── Makefile                   # up/monitoring/rules/scenario/compare/...
├── k8s/
│   ├── base/                  # namespace, Deployment, Service, NodePort
│   └── scenarios/
│       ├── A-fixed/
│       ├── B-hpa-30/ B-hpa-50/ B-hpa-70/
│       ├── C-vpa-auto/
│       ├── D-hpa-cpu-vpa-mem/
│       └── E-vpa-off/
├── monitoring/
│   ├── kube-prometheus-stack-values.yaml
│   ├── recording-rules.yaml
│   └── dashboards/            # JSON + kustomize ConfigMap
├── load/
│   ├── sample.png             # реальная тестовая картинка 709×682
│   ├── calibrate.js           # ступенчатая калибровка
│   └── spike.js               # профиль warm-up → spike → hold → tail
├── scripts/
│   ├── run-scenario.sh        # reset → overlay → k6 → snapshots → cost
│   ├── reset.sh               # удалить HPA/VPA, вернуть baseline
│   ├── calibrate.sh           # ступени 1..16 VU + CSV
│   ├── vpa-snapshot.sh        # сохранить status VPA
│   ├── cost.py                # модель стоимости
│   └── compare.py             # сводная таблица
├── results/
│   ├── <scenario>-<rep>/      # summary.json, k6.json, cost.md, vpa.json, ...
│   ├── calibration/
│   └── comparison.{csv,md}
└── docs/                      # подробные объяснения на русском
```

---

## 6. Методика: этапы 0–9

### Stage 0 — разведка

Проверены ОС, версии, allocatable, metrics-server. Выяснено, что `c5.xlarge`
недоступен; согласован `m7i-flex.large`. Получен контракт OCR-эндпоинта из
исходников приложения, а не из догадок:

- `POST /tesseract`, `multipart/form-data`;
- поле файла — `file`, поле опций — `options` (строка JSON);
- health — `GET /.well-known/health/{ready,live}` на `:8884`;
- внутри пода tesseract pool ограничен **2 процессами** (`pool.default.max=2`).

Подробно: [`docs/00-recon.md`](docs/00-recon.md).

### Stage 1 — базовые манифесты

- `Deployment/ocr`: digest образа, requests `400m/256Mi`, memory limit `384Mi`,
  CPU limit **не задан** (чтобы не добавлять CFS-throttling);
- QoS-класс — **Burstable** (requests < limits);
- `startupProbe` (до 150 с на старт), `readinessProbe` (трафик), мягкая
  `livenessProbe` (6 ошибок подряд);
- `strategy.maxSurge=0`, `maxUnavailable=1` — иначе на одном узле rolling update
  создаёт лишний под и зависает в Pending;
- `Service/ocr` ClusterIP + `Service/ocr-nodeport` для k6.

Подробно: [`docs/01-deployment.md`](docs/01-deployment.md).

### Stage 2 — VPA

Установлен VPA **1.8.1** официальным скриптом `hack/vpa-up.sh` (без аргумента
`apply` — скрипт сам его добавляет). Проверены CRD и режимы:

| Режим | Поведение |
|---|---|
| `Off` | только рекомендации |
| `Initial` | задаёт requests только при создании пода |
| `Recreate` | задаёт при создании + вытесняет поды вне границ |
| `Auto` | устарел, эквивалентен `Recreate` |
| `InPlaceOrRecreate` | сначала in-place, иначе пересоздание |
| `InPlace` | только in-place, без вытеснения |

Updater по умолчанию (`--min-replicas=2`) **не вытесняет единственный под**.
В сценарии C поэтому 2 реплики; обойти можно `spec.updatePolicy.minReplicas: 1`,
но это риск простоя.

Подробно: [`docs/02-vpa.md`](docs/02-vpa.md).

### Stage 3 — сценарии A–E

| Сценарий | Реплики | HPA | VPA | Смысл |
|---|---|---|---|---|
| `A-fixed` | 3 | — | — | baseline «всегда на максимуме» |
| `B-hpa-30/50/70` | 1..3 | CPU 30/50/70% | — | только HPA |
| `C-vpa-auto` | 2 | — | CPU+RAM, `Recreate` | только VPA |
| `D-hpa-cpu-vpa-mem` | 1..3 | CPU 50% | только RAM | разделение ресурсов |
| `E-vpa-off` | 1 | — | CPU+RAM, `Off` | только рекомендации |

HPA использует `scaleUp.stabilizationWindowSeconds: 0` и
`scaleDown: 120` — одинаково во всех B, чтобы сравнение было честным.
HPA считает утилизацию как `usage / requests`, поэтому калибровка requests
критична.

В D HPA и VPA **не управляют одним ресурсом**: HPA — CPU, VPA — память.
Иначе VPA меняет request, утилизация HPA скачет, и системы борются друг с другом.

Подробно: [`docs/03-hpa-vs-vpa.md`](docs/03-hpa-vs-vpa.md).

### Stage 4 — мониторинг

kube-prometheus-stack 93.4.1: Prometheus (48h, 15s, remote-write receiver),
Grafana, kube-state-metrics, node-exporter; Alertmanager и стандартные alert
rules отключены ради экономии CPU. Отключены scrape-таргеты etcd/controller/
scheduler/proxy, которых в k3s нет. Все **11 active targets — `up`**.

Мониторинг занимает ~430m CPU / ~930Mi RAM requests; вместе с системными подами
это ~780m CPU, поэтому OCR-подам остаётся ~1.2 CPU.

VPA-метрики отдаются через `customResourceState` KSM 2.20.0:

```
kube_verticalpodautoscaler_status_recommendation_containerrecommendations_target_cpu
kube_verticalpodautoscaler_status_recommendation_containerrecommendations_target_memory
..._lowerbound_cpu / ..._lowerbound_memory
..._upperbound_cpu / ..._upperbound_memory
```

Подробно: [`docs/04-monitoring.md`](docs/04-monitoring.md).

### Stage 5 — калибровка

Один под, без автоскейлеров, ступени 1/2/4/8/12/16 одновременных запросов
по 60 с, реальная картинка 709×682:

| VU | RPS | ошибки | p95, мс | CPU avg/max, cores | RAM max, MiB |
|---:|---:|---:|---:|---:|---:|
| 1 | 0.356 | 0% | 3036 | 1.03 / 1.42 | 88 |
| 2 | 0.384 | 0% | 5469 | 1.48 / 1.83 | 138 |
| 4 | 0.369 | 0% | 10507 | 1.68 / 1.83 | 138 |
| 8 | 0.369 | 0% | 20931 | 1.77 / 1.83 | 138 |
| 12 | 0.323 | 0% | 37753 | 1.77 / 1.84 | 140 |
| 16 | 0.246 | 12.5% | 59998 (timeout) | 1.82 / 1.84 | 140 |

Насыщение наступает уже при **1–2 VU**: пропускная способность упирается
в ~0.37 RPS, латентность растёт линейно (очередь). «Умеренной нагрузки»,
при которой под использует 30% CPU, на этом узле нет.

VPA по этим данным рекомендовал `920m CPU / 256Mi` (позже CPU-потолок снижен
до 500m, чтобы 2 пода помещались на узел).

Принятые значения: requests `400m/256Mi`, limit RAM `384Mi`. 400m — осознанный
компромисс: «правильные» ~900m оставили бы на узле только один под, и HPA
не смог бы масштабироваться вообще.

Подробно: [`docs/04-calibration.md`](docs/04-calibration.md).

### Stage 6 — нагрузка k6

`load/spike.js`, ~10 минут:

```
2 min   warm-up  0 → 1 VU
30 s    spike    1 → 10 VU
3 min   hold     10 VU
30 s    drop     10 → 1 VU
4 min   tail     1 VU
```

- `POST /tesseract` с `sample.png` (multipart), `sleep(1)`;
- пороги `http_req_failed < 5%`, `p95 < 5s` — при пике p95 заведомо выше,
  это ожидаемый результат, k6 завершается с кодом 99;
- метрики пишутся в Prometheus через `experimental-prometheus-rw`;
- имя executor'а равно имени сценария, поэтому HTTP-метрики получают тег
  `scenario=B-hpa-50` и т.п.;
- `--summary-export results/<scenario>-<rep>/k6.json`.

k6 запускается не в кластере, а на том же хосте, через NodePort 30884.

### Stage 7 — recording rules и дашборд

`monitoring/recording-rules.yaml` (envsubst из `env.sh`):

```
ocr:cpu_requests_cores, ocr:mem_requests_bytes
ocr:cpu_usage_cores,    ocr:mem_usage_bytes
ocr:cpu_share, ocr:mem_share
ocr:alloc_share = max(cpu_share, mem_share)
ocr:allocated_cost_per_hour = alloc_share * node_price
ocr:cpu_utilization = usage / requests
ocr:pending_pods, ocr:replicas_available
```

Дашборд `monitoring/dashboards/ocr-autoscaling.json` (16 панелей, sidecar
Grafana + ConfigMap с меткой `grafana_dashboard=1`): нагрузка VU/RPS, p95,
ошибки, реплики/Pending, CPU usage vs requests, утилизация HPA, RAM,
throttling, рестарты и причины, VPA target/lower/upper, стоимость.
Переменная `scenario` фильтрует k6-панели; аннотации `ocr-run` отмечают
границы прогонов.

Подробно: [`docs/05-dashboard.md`](docs/05-dashboard.md).

### Stage 8 — стоимость

```
node_cost       = P * T
cpu_share(t)    = Σ cpu_requests(t) / NODE_VCPU
mem_share(t)    = Σ mem_requests(t) / NODE_RAM
alloc_share(t)  = max(cpu_share, mem_share)
allocated_cost  = P * ∫ alloc_share(t) dt
idle_cost       = node_cost - allocated_cost
cost_per_1k     = allocated_cost / (успешные_запросы / 1000)
efficiency      = ∫ реальное_использование dt / ∫ requests dt
```

- `node_cost` — реальный счёт EC2, **не зависит от числа подов**;
- `allocated_cost` — модель «сколько стоили бы зарезервированные ресурсы,
  если бы узел масштабировался»;
- доминирующий ресурс `max(...)`, а не взвешенная сумма: под ограничен тем,
  чего не хватает первым.

На 10 минут при $0.10175/ч `node_cost ≈ $0.0170`. Дополнительно в реальном
счёте: EBS 30 GiB (~$2.4/мес), публичный IPv4 (~$3.65/мес), egress.

Подробно: [`docs/06-cost.md`](docs/06-cost.md).

### Stage 9 — оркестрация и прогоны

`scripts/run-scenario.sh <scenario> <rep>`:

1. `reset.sh`: удаляет HPA/VPA, возвращает 1 реплику, ждёт rollout, cooldown 180 с.
2. Применяет overlay, ждёт готовности.
3. Проверяет Prometheus remote-write и health через NodePort.
4. Запускает k6 ~10 минут, фиксирует start/end.
5. Сохраняет `vpa.json`, `pods.txt`, `deployment.yaml`, `hpa.yaml`.
6. Создаёт аннотацию в Grafana.
7. Вызывает `cost.py`, пишет `summary.json`.
8. `make compare` строит `results/comparison.{csv,md}`.

---

## 7. Сценарии A–E подробнее

### A-fixed

3 реплики, без автоскейлеров. Это «всегда на максимуме» — столько же, сколько
HPA может выставить на этом узле. Показывает цену отсутствия гибкости.

### B-hpa-30 / 50 / 70

Только HPA, `minReplicas=1`, `maxReplicas=3`, target 30/50/70%.
Единое поведение scale up/down. При request 400m и реальном потреблении
~1.8 ядра утилизация кратно выше любого порога, поэтому все три варианта
быстро упираются в `maxReplicas=3`.

### C-vpa-auto

2 фиксированные реплики, VPA `Recreate`, контролирует CPU и RAM,
`RequestsAndLimits`, `minAllowed 250m/256Mi`, `maxAllowed 500m/2Gi`.
Две реплики нужны, чтобы updater мог вытеснять под, не роняя сервис
(`--min-replicas=2`).

VPA рекомендовал 500m/256Mi, но **не вытеснял поды**: requests 400m находились
внутри `[250m, 500m]`. Это нормальное поведение — VPA не гоняет под к target,
если текущий request допустим.

### D-hpa-cpu-vpa-mem

HPA по CPU 50% + VPA только по памяти (`controlledResources: ["memory"]`).
Разделение ресурсов исключает конфликт. VPA-память осталась 256Mi, рестартов 0.

### E-vpa-off

VPA в `Off`: только рекомендации, 1 реплика, без HPA. Самый дешёвый по
зарезервированным ресурсам и при этом с той же пропускной способностью.
Минус — нет отказоустойчивости и автоскейлинга.

---

## 8. Интерпретация результатов

1. **CPU — узкое место.** Все сценарии дают ~0.26 RPS; разница в p95
   (24–41 с) не компенсируется числом подов. 2 ядра уже заняты одним-двумя
   OCR-запросами (tesseract — CPU-bound).
2. **HPA работает механически, но не даёт ёмкости.** Он дошёл до 3 реплик,
   Pending не было, однако throughput не вырос: новые поды делят те же ядра.
3. **A и D хуже B.** Вероятно, 3 пода работают с самого начала и создают
   6 конкурирующих OCR-процессов на 2 ядрах; HPA же добавляет поды постепенно.
   Плюс шум одной повторности — различия 24 vs 40 с могут быть нестабильны.
4. **VPA точен.** Target 500m CPU против базовых 400m; память 256Mi совпала
   с ручным значением. Применять 500m в базе нельзя без потери 3-й реплики:
   3×500m + 780m > 2000m.
5. **Стоимость.** E дешевле B примерно в 2.4 раза по `$/1k` при сопоставимой
   латентности. HPA резервирует в 2.5 раза больше ресурсов без прироста RPS.

### Итоговая рекомендация

- **Для экономии:** E (1 реплика + VPA-рекомендации) или C (2 реплики, VPA),
  с оговоркой про отказоустойчивость.
- **Для латентности:** B-hpa-30/50 — HPA держит 3 реплики на пике; выигрыш
  на этом узле небольшой.
- **Что реально поможет:** узел 4+ vCPU или несколько узлов + Cluster
  Autoscaler/Karpenter; тогда HPA будет добавлять *ёмкость*, а не только поды.
  VPA-рекомендации стоит внедрять после увеличения узла.

---

## 9. Ограничения

- Один узел **2 vCPU / 8 GiB**; `c5.xlarge` был недоступен.
- k6 и Prometheus работают на том же узле и конкурируют за CPU.
- **Одна повторность** на сценарий; для статистики нужно ≥3 (`REP=2`, `REP=3`).
  Различия в p95 следует считать предварительными.
- `maxReplicas=3` — потолок из-за allocatable (1980m requests из 2000m).
- VPA CPU `maxAllowed=500m` — искусственное ограничение ради размещения подов.
- Регион AWS в `env.sh` указан предположительно (`eu-west-1`); на манифесты
  и расчёты не влияет, цену пользователь подтвердил отдельно.
- Grafana/Prometheus в лаборатории были временно открыты в SG; это не
  продакшн-конфигурация.

---

## 10. Как воспроизвести

Требуется Ubuntu-хост с sudo, доступом в интернет и установленным `make`
(на чистой машине: `sudo apt-get install -y make git curl jq openssl gettext-base python3`).

```bash
git clone git@github.com:yera-mukan/CSS447-General-Project.git
cd CSS447-General-Project

make up          # tools (helm,k6) + k3s + VPA + base + monitoring + rules + dashboard
make status      # узлы, Deployment, поды, сервисы
make health      # health-эндпоинт приложения

# калибровка (нужны port-forward'ы, см. docs/04-calibration.md)
make scenario SCENARIO=B-hpa-50 REP=1
make compare
```

Полезные цели:

| Команда | Действие |
|---|---|
| `make monitoring` | установить/обновить kube-prometheus-stack |
| `make rules` | применить recording rules (envsubst из `env.sh`) |
| `make dashboard` | применить ConfigMap дашборда |
| `make reset` | удалить HPA/VPA, вернуть 1 реплику + cooldown |
| `make scenario SCENARIO=C-vpa-auto REP=1` | один прогон |
| `make compare` | пересобрать сводную таблицу |
| `make top` / `make logs` / `make events` | диагностика |

Полный прогон одного сценария — ~13–15 минут (3 минуты reset + 10 минут k6).

---

## 11. Доступ к Grafana и Prometheus

В лаборатории port-forward'ы запущены systemd-сервисами на `0.0.0.0`:

- Grafana — `http://<ec2-public-ip>:13000`, `admin` / `ocrlab`;
- Prometheus — `http://<ec2-public-ip>:19090`.

Актуальный публичный IP на момент работы: `16.192.176.90`
(может измениться после stop/start инстанса; тогда поправить `root_url`
в `monitoring/kube-prometheus-stack-values.yaml` и выполнить `make monitoring`).

Сервисы:

```bash
sudo systemctl status grafana-port-forward prometheus-port-forward
sudo systemctl restart grafana-port-forward
```

Безопасный вариант — SSH-туннель:

```bash
ssh -L 13000:127.0.0.1:13000 -L 19090:127.0.0.1:19090 ubuntu@<ec2-public-ip>
```

> Grafana с лимитом 256Mi падала `OOMKilled` и показывала «failed to load its
> application files». Лимит поднят до **768Mi**; это обязательный минимум.

---

## 12. Глоссарий

- **Pod** — минимальная единица запуска: контейнер(ы) с общей сетью.
- **Deployment** — менеджер подов: держит нужное число реплик, обновляет образ.
- **Service** — стабильный виртуальный IP/имя, балансирует трафик по Ready-подам.
- **Node** — виртуальная машина (EC2), на которой работают поды.
- **requests** — гарантированный резерв CPU/RAM; HPA считает утилизацию от него.
- **limits** — верхняя граница: RAM → `OOMKilled`, CPU → throttling.
- **allocatable** — ресурсы узла, реально доступные подам после системного резерва.
- **QoS Burstable** — requests < limits; под может использовать больше запрошенного,
  но при нехватке ресурсов вытесняется раньше Guaranteed.
- **stabilization window** — окно, в котором HPA учитывает прошлые рекомендации,
  чтобы не дёргать реплики (у нас scale-down 120 с).
- **VPA lowerBound/target/upperBound** — минимальная, рекомендуемая и максимальная
  границы requests.
- **Pending** — под создан, но планировщик не нашёл места на узле.
- **Throttling** — принудительное ограничение CPU через CFS; причина — CPU limit
  или перегруженный узел.
- **OOMKilled** — контейнер убит из-за превышения memory limit.

---

## 13. Документация

| Файл | Содержание |
|---|---|
| [`docs/00-recon.md`](docs/00-recon.md) | разведка, железо, контракт OCR, термины |
| [`docs/01-deployment.md`](docs/01-deployment.md) | base-манифесты, пробы, QoS, деплой |
| [`docs/02-vpa.md`](docs/02-vpa.md) | установка VPA, режимы, min-replicas |
| [`docs/03-hpa-vs-vpa.md`](docs/03-hpa-vs-vpa.md) | сценарии A–E, почему нельзя делить ресурс |
| [`docs/04-monitoring.md`](docs/04-monitoring.md) | Prometheus/Grafana, targets, VPA-метрики |
| [`docs/04-calibration.md`](docs/04-calibration.md) | калибровка, таблица, выбор requests |
| [`docs/05-dashboard.md`](docs/05-dashboard.md) | панели дашборда, как добавить метрику |
| [`docs/06-cost.md`](docs/06-cost.md) | формулы стоимости и их смысл |
| [`docs/07-results.md`](docs/07-results.md) | результаты, выводы, ограничения |

Сырые данные: [`results/`](results) — `k6.json`, `cost.md`, `cost.json`,
`vpa.json`, `summary.json`, `pods.txt`, `comparison.csv`.

---

## 14. Итог одной фразой

На одноузловом стенде HPA и VPA работают корректно, но **CPU-bound OCR
упирается в 2 ядра**: реплики не добавляют RPS, а только резервируют ресурсы.
Самый экономичный режим — одна реплика с VPA-рекомендациями (E), а для
реального масштабирования нужен узел крупнее или несколько узлов
с Cluster Autoscaler.
