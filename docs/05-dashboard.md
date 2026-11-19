# Stage 7 — recording rules и дашборд

## Recording rules

`monitoring/recording-rules.yaml` — это `PrometheusRule` с меткой `release: kps`
(по ней kube-prometheus-stack выбирает правила). Применяется командой:

```bash
make rules
# внутри: envsubst '${NODE_PRICE_PER_HOUR} ${NODE_VCPU} ${NODE_RAM_GIB}' \
#           < monitoring/recording-rules.yaml | kubectl apply -f -
```

Правила (интервал 30 с):

| Метрика | Смысл |
|---|---|
| `ocr:node_price_per_hour`, `ocr:node_vcpu`, `ocr:node_ram_bytes` | константы узла из `env.sh` |
| `ocr:cpu_requests_cores`, `ocr:mem_requests_bytes` | сумма requests контейнеров `ocr` |
| `ocr:cpu_usage_cores`, `ocr:mem_usage_bytes` | реальное потребление |
| `ocr:cpu_share`, `ocr:mem_share` | доля ресурсов узла |
| `ocr:alloc_share` | `max(cpu_share, mem_share)` — доминирующий ресурс |
| `ocr:allocated_cost_per_hour` | `alloc_share * цена_узла` |
| `ocr:cpu_utilization` | `usage / requests` — то же, что видит HPA |
| `ocr:pending_pods`, `ocr:replicas_available` | давление на планировщик |

Почему доминирующий ресурс, а не взвешенная сумма: под не может использовать
больше CPU, чем ему выделено, даже если памяти в избытке; «бутылочное горлышко» —
это максимум из двух долей. Вес 50/50 был бы произвольным.

## Дашборд

`monitoring/dashboards/ocr-autoscaling.json` + kustomize `configMapGenerator`
с меткой `grafana_dashboard: "1"`. Sidecar Grafana сам подхватывает ConfigMap
из любого namespace (`searchNamespace: ALL`).

```bash
make dashboard
# Grafana -> Dashboards -> "OCR autoscaling lab (k3s, single node)"
```

Переменная **`scenario`** (`All` или конкретный прогон) фильтрует панели k6:
она берётся из тега `scenario`, который k6 присваивает метрикам (имя executor'а
равно имени сценария — см. `load/spike.js`).

### Как читать панели

1. **Load: k6 VUs / RPS** — профиль нагрузки. Видно warm-up, пик, спад, хвост.
2. **Latency p95 / Error rate** — качество обслуживания глазами клиента.
   На этом узле p95 десятки секунд: нагрузка выше реальной ёмкости.
3. **Replicas / Pending** — что сделали HPA/Deployment и уместились ли поды
   на узел. `Pending > 0` = упёрлись в allocatable.
4. **CPU usage vs requests** — сколько реально съедено против зарезервированного.
5. **CPU utilization** — ровно сигнал HPA; >100% значит requests ниже реального
   потребления.
6. **RAM usage vs requests/limits** — запас до OOMKilled.
7. **Throttling** — доля CFS-периодов, в которых под тормозили. У нас CPU limit
   не задан, поэтому throttling около нуля; всплески означают, что узел сам
   перегружен.
8. **Restarts / Last termination reasons** — причина рестартов: `OOMKilled`,
   `Error`, `Completed`. Вытеснение VPA тоже даёт рестарт, но причина будет
   `Error`/`Completed`, а не `OOMKilled`; смотрите также панель VPA.
9. **VPA CPU/RAM** — `target/lowerBound/upperBound` против текущих requests.
10. **Cost** — `allocated_cost_per_hour` (модель) и цена узла; вторая панель
    интегрирует по выбранному диапазону.

Аннотации `ocr-run` создаются `run-scenario.sh` через Grafana API (красные
метки на графиках) и показывают границы каждого прогона.

### Как добавить свою метрику

1. Проверить PromQL в Prometheus (`/graph`), например:
   `sum(rate(container_cpu_usage_seconds_total{namespace="ocr-lab",container="ocr"}[1m]))`.
2. Grafana → нужная панель → Edit → добавить query, задать legend, unit.
3. Save. Затем экспортировать JSON:
   `curl -u admin:ocrlab localhost:13000/api/dashboards/uid/ocr-autoscaling-lab | jq '.dashboard' > monitoring/dashboards/ocr-autoscaling.json`
4. `make dashboard` (ConfigMap пересоздастся, sidecar перезагрузит дашборд).
5. Закоммитить JSON. Не редактируйте ConfigMap руками — источник правды JSON.

> Важно: k6-метрики имеют тег `scenario`, а метрики Kubernetes — нет.
> Поэтому панели ресурсов показывают весь namespace, а не только выбранный
> сценарий; для разделения прогонов используйте временной диапазон/аннотации.
