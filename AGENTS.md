# Промпт для DeepSeek: лаборатория автоскейлинга OCR (k3s на AWS EC2)

---

## 1. Роль и цель

Ты помогаешь мне построить воспроизводимый стенд на **k3s (один узел на AWS EC2)**, чтобы
сравнить стратегии автоскейлинга для OCR-сервиса под сильной нагрузкой:

- **A** — фиксированные реплики (baseline);
- **B** — только **HPA** (CPU target 30 / 50 / 70%);
- **C** — только **VPA** (режим Auto);
- **D** — **HPA по CPU + VPA только по памяти**;
- **E** — **VPA в режиме Off** (только рекомендации), потом повтор B с исправленными requests.

Сравниваем: p95 латентность, процент ошибок, число реплик, requests/limits, реальное
использование CPU/RAM, рестарты подов, **расчётную стоимость** (как считать, см. Stage 8).

**Я новичок в Kubernetes.** Моя цель не только получить цифры, но и понять систему.
Поэтому:
- каждый YAML сопровождай комментариями (на английском) о том, что делает каждое поле;
- после каждого stage создай `docs/NN-<тема>.md` на **русском**: что мы сделали, какие объекты
  Kubernetes создали, как они связаны, какие команды `kubectl` смотреть для проверки;
- когда вводишь новый термин (requests, limits, QoS, throttling, OOMKilled, stabilization window),
  объясни его в 1–2 предложениях на простом языке.

## 2. Контекст стенда

| Параметр | Значение |
|---|---|
| Приложение | `ferraripupu/ocr-app` (OCR по HTTP), порт `8884` |
| Readiness | `GET /.well-known/health/ready` на `:8884` |
| Liveness | `GET /.well-known/health/live` на `:8884` |
| Кластер | k3s, один узел (server) на EC2 |
| Генератор нагрузки | **отдельная** EC2 в том же регионе/AZ (k6 запускается там, НЕ в кластере) |
| Тип инстанса / цена | задаются в `env.sh` (см. ниже), не хардкодить в манифестах |
| Namespace приложения | `ocr-lab` |

`env.sh` (создай и используй везде через `source env.sh`):

```bash
export INSTANCE_TYPE="c5.xlarge"   # не t3: у burstable CPU кончаются кредиты и результаты искажаются
export NODE_VCPU=4
export NODE_RAM_GIB=8
export NODE_PRICE_PER_HOUR=0.17    # USD/час on-demand Linux; ПРОВЕРИТЬ в AWS Pricing Calculator для моего региона
export AWS_REGION="<fill>"
export NAMESPACE="ocr-lab"
export OCR_IMAGE="ferraripupu/ocr-app:latest"  # на Stage 1 предложи зафиксировать тег или digest
```

## 3. Правила работы

1. **Работай по stages (ниже). После каждого stage остановись**, покажи что сделано, как проверить
   и спроси, идти ли дальше. Не перескакивай.
2. Все скрипты идемпотентны (можно запускать повторно). Все команды собери в `Makefile`.
3. Ничего деструктивного без моего подтверждения (удаление namespace, `helm uninstall` и т.п.).
4. **Безопасность:** порт 8884 и Prometheus/Grafana не открывать в интернет. Доступ только через
   SSH-туннель или по security group с IP генератора нагрузки. Если нужен NodePort, объясни риск.
5. Не выдумывай: если не уверен в имени метрики, версии CRD или значении Helm, **проверь в
   документации/`kubectl explain`/`helm show values`** и скажи мне, что именно проверил.
6. Закрепляй версии (Helm charts, VPA, образы), чтобы эксперименты были воспроизводимы.
7. Если что-то из моего плана неосуществимо на моём железе (например, поды не помещаются на узел),
   скажи об этом прямо и предложи варианты.

## 4. Структура репозитория

```
.
├── CLAUDE.md
├── Makefile
├── env.sh
├── docs/                      # 00-..., 01-... объяснения на русском
├── k8s/
│   ├── base/                  # namespace, deployment, service
│   ├── scenarios/
│   │   ├── A-fixed/
│   │   ├── B-hpa-30/  B-hpa-50/  B-hpa-70/
│   │   ├── C-vpa-auto/
│   │   ├── D-hpa-cpu-vpa-mem/
│   │   └── E-vpa-off/
├── monitoring/
│   ├── kube-prometheus-stack-values.yaml
│   ├── recording-rules.yaml
│   └── dashboards/ocr-autoscaling.json   # + ConfigMap для sidecar Grafana
├── load/
│   └── spike.js               # k6
├── scripts/
│   ├── run-scenario.sh
│   ├── reset.sh
│   ├── vpa-snapshot.sh
│   └── cost.py
└── results/                   # <scenario>-<rep>/ summary.json, k6.json, vpa.json, cost.md
```

## 5. Stage 0 — разведка и вопросы (ничего не меняем)

- Покажи версии: `k3s --version`, `kubectl version`, ОС, `nproc`, `free -h`.
- `kubectl get nodes -o wide`, `kubectl describe node` и вычисли **allocatable** CPU и RAM
  (это то, что реально доступно подам после системных нужд).
- Проверь, что `metrics-server` работает: `kubectl top nodes`.
- Объясни мне простыми словами разницу pod / deployment / service / node / requests / limits.
- **Задай мне вопросы** и дождись ответов:
  1. Какой endpoint и формат запроса у OCR (multipart-файл, base64?), пример ответа, нужен ли
     ключ? Дай мне пример картинки для теста или попроси прислать.
  2. Какой инстанс и регион использую для цены?
  3. Где находится машина с k6 и её приватный IP?

## 6. Stage 1 — base-манифесты

Создай `k8s/base/` и kustomization. Шаблон Deployment (значения requests помечены временными,
они будут уточнены на Stage 5):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ocr
  namespace: ocr-lab
  labels: { app: ocr }
spec:
  replicas: 1                      # сценарии переопределяют
  selector:
    matchLabels: { app: ocr }
  template:
    metadata:
      labels: { app: ocr }
    spec:
      containers:
      - name: ocr
        image: ferraripupu/ocr-app:latest   # TODO: pin tag/digest
        imagePullPolicy: IfNotPresent       # не тянуть образ при каждом старте пода
        ports:
        - containerPort: 8884
        resources:
          requests:                         # HPA считает утилизацию ОТ этого значения
            cpu: 500m                       # TEMP, calibrate on Stage 5
            memory: 512Mi                   # TEMP
          limits:
            memory: 1Gi                     # превышение = OOMKilled (рестарт)
            # CPU limit намеренно не задаём на старте: CPU limit вызывает throttling.
            # Отдельным экспериментом можно проверить влияние CPU limit.
        startupProbe:                       # даёт приложению время загрузиться, пока liveness молчит
          httpGet: { path: /.well-known/health/ready, port: 8884 }
          periodSeconds: 5
          failureThreshold: 30
        readinessProbe:                     # решает, получает ли под трафик
          httpGet: { path: /.well-known/health/ready, port: 8884 }
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 3
        livenessProbe:                      # решает, нужно ли убить под
          httpGet: { path: /.well-known/health/live, port: 8884 }
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 6               # мягко: под нагрузкой liveness не должен давать ложные рестарты
---
apiVersion: v1
kind: Service
metadata:
  name: ocr
  namespace: ocr-lab
spec:
  selector: { app: ocr }
  ports:
  - port: 8884
    targetPort: 8884
```

Проверь: `kubectl -n ocr-lab rollout status deploy/ocr`, `kubectl -n ocr-lab get pods`, вызов
health-эндпоинта через `kubectl port-forward`. В документе `docs/01-deployment.md` объясни
каждый блок и почему пробы настроены именно так.

## 7. Stage 2 — VPA

VPA не входит в k3s. Установи его из официального репозитория `kubernetes/autoscaler`
(каталог `vertical-pod-autoscaler`, скрипт `hack/vpa-up.sh`; нужен `openssl`) на **закреплённой
версии**. Проверь, что поднялись три компонента: `vpa-recommender`, `vpa-updater`,
`vpa-admission-controller`, и что `kubectl get crd | grep verticalpodautoscaler` непустой.

Выясни и сообщи мне:
- совместимость версии VPA с моей версией k8s/k3s;
- какие `updateMode` доступны в установленной версии (`Off`, `Initial`, `Recreate`, `Auto`,
  а также режим изменения размера пода «на месте», если версия и k8s это поддерживают);
- как ведёт себя updater при `replicas: 1` (по умолчанию он не вытесняет единственный под;
  объясни, как это обойти для эксперимента C).

## 8. Stage 3 — сценарии A–E (kustomize overlays)

Каждый сценарий = overlay над `base`. Запуск: `kubectl apply -k k8s/scenarios/<name>`.

### A-fixed: фиксированные реплики
Только patch `replicas: N`. N вычисляется на Stage 5 (число подов, нужное для пика).
Без HPA и VPA.

### B-hpa-{30,50,70}: только HPA
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ocr
  namespace: ocr-lab
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: ocr }
  minReplicas: 1
  maxReplicas: 6          # ВАЖНО: не больше, чем реально помещается на узел (см. правило ниже)
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 50     # 30 / 50 / 70 в трёх overlay
  behavior:                         # ОДИНАКОВЫЙ во всех HPA-сценариях, иначе сравнение нечестное
    scaleUp:   { stabilizationWindowSeconds: 0 }
    scaleDown: { stabilizationWindowSeconds: 120 }
```
**Правило про maxReplicas:** посчитай `floor(allocatable_cpu / cpu_request)` с запасом на
мониторинг. Поды сверх этого уйдут в `Pending`. Это не ошибка стенда, а важный результат
(на одном узле HPA упирается в потолок; для реального выхода нужен Cluster Autoscaler/Karpenter
или несколько узлов). Выведи число Pending-подов в метрики и дашборд.

### C-vpa-auto: только VPA
Фиксированные `replicas: 2` (чтобы updater мог вытеснять поды, не обрушивая сервис), без HPA.
```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: ocr
  namespace: ocr-lab
spec:
  targetRef: { apiVersion: apps/v1, kind: Deployment, name: ocr }
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
    - containerName: ocr
      minAllowed: { cpu: 250m, memory: 256Mi }
      maxAllowed: { cpu: "2",  memory: 3Gi }   # подбери по allocatable
      controlledResources: ["cpu", "memory"]
      controlledValues: RequestsAndLimits
```

### D-hpa-cpu-vpa-mem: HPA по CPU + VPA только по памяти
HPA как в B-hpa-50 (или лучшем из B), плюс VPA с
`controlledResources: ["memory"]`. **VPA и HPA не должны управлять одним ресурсом**
(иначе борются друг с другом). Объясни это в `docs/03-hpa-vs-vpa.md`.

### E-vpa-off: только рекомендации
То же VPA, но `updateMode: "Off"`. VPA ничего не меняет, но показывает
`kubectl describe vpa ocr` (lowerBound / target / upperBound). После прогона перенеси
рекомендованные requests в base и повтори B-hpa-50. Это и есть сравнение «до/после
правильного размера requests».

## 9. Stage 4 — мониторинг

Установи `kube-prometheus-stack` через Helm (закрепи версию chart). `monitoring/kube-prometheus-stack-values.yaml`:
- `retention: 48h`, `scrapeInterval: 15s`, умеренные resource requests/limits для Prometheus и Grafana
  (узел маленький, мониторинг не должен съедать эксперимент; сообщи мне, сколько он потребляет);
- `prometheus.prometheusSpec.enableRemoteWriteReceiver: true` (чтобы k6 мог писать метрики);
- Grafana sidecar для дашбордов включён (дашборды подхватываются из ConfigMap с label `grafana_dashboard: "1"`);
- доступ к Grafana/Prometheus только через `kubectl port-forward` + SSH-туннель.

**Метрики VPA-рекомендаций** (kube-state-metrics по умолчанию их не отдаёт): настрой
`customResourceState` для `autoscaling.k8s.io/v1 VerticalPodAutoscaler` и выдай как gauge
`target` / `lowerBound` / `upperBound` по `cpu` и `memory` (путь
`status.recommendation.containerRecommendations`) плюс RBAC на чтение VPA. Проверь по текущей
документации kube-state-metrics (формат конфига менялся между версиями). Если не получается за
разумное время, напиши лёгкий fallback: `scripts/vpa-snapshot.sh` или маленький Python-экспортёр,
который читает `kubectl get vpa -o json` каждые 15 с.

Проверь в Prometheus (Status → Targets, и запросами), что доступны:
`kube_pod_container_resource_requests`, `kube_pod_container_resource_limits`,
`container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`,
`container_cpu_cfs_throttled_periods_total`, `kube_pod_container_status_restarts_total`,
`kube_pod_container_status_last_terminated_reason`,
`kube_horizontalpodautoscaler_status_current_replicas`, `kube_deployment_status_replicas`,
`kube_pod_status_phase`.

## 10. Stage 5 — калибровочный прогон (обязательный)

Без него requests будут «с потолка», и HPA посчитает утилизацию неправильно.
1. Один под, без автоскейлеров. Ступенчато увеличивай число одновременных запросов (1, 2, 4, 8, 16…).
2. Запиши для каждой ступени: CPU пода, RAM пода, p95, ошибки, пропускную способность (RPS).
3. Найди точку, где латентность начинает расти (насыщение), и реальные пики CPU/RAM.
4. Предложи: начальные `requests` (≈ типичное потребление под умеренной нагрузкой),
   `limits` по памяти (пик + запас ~30%), число VU для «пика» в k6, число реплик N для сценария A.
5. Покажи мне таблицу и **жди подтверждения** перед записью в base.

## 11. Stage 6 — нагрузка k6 (запускается на отдельной машине)

`load/spike.js` — профиль одинаков во всех прогонах (~10 минут): разогрев → резкий пик → спад → хвост.
```js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    spike: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '2m',  target: 5 },    // warm-up
        { duration: '30s', target: 40 },   // spike (число VU уточнить на Stage 5)
        { duration: '3m',  target: 40 },   // hold
        { duration: '30s', target: 5 },    // drop
        { duration: '4m',  target: 5 },    // tail: смотрим scale-down
      ],
    },
  },
  thresholds: {
    http_req_failed:   ['rate<0.05'],
    http_req_duration: ['p(95)<5000'],
  },
};

export default function () {
  // TODO: заменить на реальный OCR-запрос по ответам со Stage 0 (multipart/base64).
  // Картинку загрузить один раз в init-контексте через open(..., 'b').
  const res = http.post(`${__ENV.TARGET}/<ocr-endpoint>`, /* payload */ null);
  check(res, { 'status 200': (r) => r.status === 200 });
  sleep(1);
}
```
Запуск (в Prometheus, через приватный IP узла и NodePort, доступный по security group только
генератору): 
`K6_PROMETHEUS_RW_SERVER_URL=http://<node-private-ip>:<port>/api/v1/write k6 run -o experimental-prometheus-rw --tag scenario=<name> --tag rep=<n> load/spike.js`.
Также сохраняй `--summary-export results/<name>-<rep>/k6.json`. Проверь точные имена k6-метрик
в Prometheus после первого запуска (например `k6_http_req_duration_p95`).

## 12. Stage 7 — recording rules и дашборд

`monitoring/recording-rules.yaml` (PrometheusRule). Цена и размер узла подставляются из `env.sh`
через `envsubst`. Примеры правил:

```promql
# константы узла
ocr:node_price_per_hour            = vector(${NODE_PRICE_PER_HOUR})
ocr:node_vcpu                      = vector(${NODE_VCPU})
ocr:node_ram_bytes                 = vector(${NODE_RAM_GIB} * 1024 * 1024 * 1024)

# суммарные requests приложения
ocr:cpu_requests_cores = sum(kube_pod_container_resource_requests{namespace="ocr-lab",container="ocr",resource="cpu"})
ocr:mem_requests_bytes = sum(kube_pod_container_resource_requests{namespace="ocr-lab",container="ocr",resource="memory"})

# доли узла
ocr:cpu_share = ocr:cpu_requests_cores / on() ocr:node_vcpu
ocr:mem_share = ocr:mem_requests_bytes / on() ocr:node_ram_bytes

# аллоцированная стоимость в $/час (взвешенная; вес CPU w=0.5, подберите и объясните выбор)
ocr:allocated_cost_per_hour = (0.5 * ocr:cpu_share + 0.5 * ocr:mem_share) * on() ocr:node_price_per_hour
```

Дашборд `monitoring/dashboards/ocr-autoscaling.json` + ConfigMap (label `grafana_dashboard: "1"`),
переменная `scenario`. Панели (все на общей временной оси, чтобы видеть причины и следствия):

1. **Нагрузка:** VU k6 и RPS.
2. **Латентность:** p95 (из k6), процент ошибок.
3. **Реплики:** `kube_deployment_status_replicas`, `kube_horizontalpodautoscaler_status_desired_replicas`,
   и отдельно число `Pending`-подов (`kube_pod_status_phase{phase="Pending"}`).
4. **CPU:** суммарное использование `sum(rate(container_cpu_usage_seconds_total{namespace="ocr-lab",container="ocr"}[1m]))`
   против суммарных requests; утилизация = usage/requests (то, на что смотрит HPA).
5. **RAM:** `container_memory_working_set_bytes` против requests и limits.
6. **Throttling:** `sum(rate(container_cpu_cfs_throttled_periods_total{...}[1m])) / sum(rate(container_cpu_cfs_periods_total{...}[1m]))`.
7. **Рестарты:** `sum(increase(kube_pod_container_status_restarts_total{namespace="ocr-lab",container="ocr"}[5m]))`
   и таблица причин (`kube_pod_container_status_last_terminated_reason`: OOMKilled, Error, Completed).
   Рестарты из-за VPA (вытеснение) отличай от аварийных (OOMKilled/пробы).
8. **VPA:** target / lowerBound / upperBound по CPU и памяти против текущих requests.
9. **Стоимость:** `ocr:allocated_cost_per_hour` (линия), накопленная стоимость за выбранный интервал
   `avg_over_time(ocr:allocated_cost_per_hour[$__range]) * ($__range_s / 3600)`, фиксированная
   стоимость узла `ocr:node_price_per_hour * ($__range_s / 3600)`, и «простаивающая» часть
   (узел минус аллоцированное).
10. Аннотации начала/конца прогона (из `run-scenario.sh` через Grafana API).

Объясни в `docs/05-dashboard.md`, как читать каждую панель и как добавить свою метрику
(как написать PromQL → добавить панель → сохранить JSON в репозиторий).

## 13. Stage 8 — расчёт стоимости EC2 (`scripts/cost.py`)

Реализуй расчёт и **объясни формулы мне на русском** в `docs/06-cost.md`.

Входные данные: `start`, `end` (UTC), URL Prometheus, значения из `env.sh`, `k6.json`.
Шаги: запроси из Prometheus range-запросом (step=15s) `ocr:cpu_requests_cores`,
`ocr:mem_requests_bytes`, и посчитай интеграл по времени (метод прямоугольников/трапеций).

Формулы (T = длительность в часах, P = цена узла $/час):

```
node_cost       = P × T                                  # то, что реально платим за узел
cpu_share(t)    = Σ cpu_requests(t) / NODE_VCPU
mem_share(t)    = Σ mem_requests(t) / NODE_RAM
alloc_share(t)  = max(cpu_share, mem_share)              # «доминирующий ресурс»; вариант: взвешенная сумма
allocated_cost  = P × ∫ alloc_share(t) dt                # стоимость ресурсов, которые зарезервировали наши поды
idle_cost       = node_cost − allocated_cost             # оплаченное, но не зарезервированное
cost_per_1k_req = allocated_cost / (успешные_запросы / 1000)
efficiency      = ∫ реальное_usage dt / ∫ requests dt    # насколько requests соответствуют реальному использованию
```

Выведи в `results/<scenario>-<rep>/cost.md` и в общую таблицу сравнения: длительность, node_cost,
allocated_cost, idle_cost, cost_per_1k_req, средние/пиковые реплики, p95, процент ошибок,
число рестартов (по причинам), число секунд в Pending, время от начала пика до первого нового
Ready-пода. Объясни, **почему реальный счёт AWS не меняется от числа реплик на одном узле**
(HPA/VPA меняют поды, а не EC2) и что allocated_cost моделирует «что было бы, если бы узлы тоже
масштабировались». Упомяни прочие статьи реального счёта (EBS, публичный IPv4, трафик).

Сделай sanity check: `node_cost` должен совпадать с тем, что покажет AWS Cost Explorer по
тегу инстанса (данные в Cost Explorer приходят с задержкой).

## 14. Stage 9 — оркестрация прогонов

`scripts/run-scenario.sh <scenario> <rep>`:
1. `reset.sh`: удалить HPA/VPA предыдущего сценария, вернуть 1 реплику (или N для A), дождаться Ready,
   подождать 3–5 мин «остывания» (чтобы рекомендации VPA и stabilization window не переносились между прогонами).
2. Убедиться, что образ уже скачан на узле (прогрев), иначе первое масштабирование измерит скорость сети.
3. Применить overlay, дождаться готовности.
4. Зафиксировать `start`, поставить аннотацию в Grafana.
5. Напомнить мне/запустить через SSH k6 на генераторе.
6. По окончании зафиксировать `end`, вызвать `vpa-snapshot.sh` (для C, D, E) и `cost.py`.
7. Сложить всё в `results/<scenario>-<rep>/`.

`make compare` строит общую таблицу (CSV + Markdown) по всем прогонам и выводит среднее ± разброс
по 3 повторам каждого сценария. Для сценариев B повторить по 30 / 50 / 70.

## 15. Definition of done

- [ ] `make up` поднимает кластер-приложение и мониторинг с нуля.
- [ ] Каждый сценарий A–E запускается одной командой и воспроизводим.
- [ ] Дашборд показывает все метрики из Stage 7 на общей временной оси.
- [ ] `results/` содержит таблицу сравнения с p95, ошибками, репликами, requests/limits, рестартами и стоимостью.
- [ ] В `docs/` есть русскоязычные объяснения, по которым я могу сам пересказать, как работают HPA, VPA и расчёт стоимости.
- [ ] В конце — краткая таблица выводов: какая стратегия лучше по цене и по латентности и **почему**
      (с оговорками про ограничения одного узла и потолок maxReplicas).
