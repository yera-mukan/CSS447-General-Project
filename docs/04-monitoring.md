# Stage 4 — мониторинг (kube-prometheus-stack)

## Что установлено

- Helm-чарт **`kube-prometheus-stack 93.4.1`** (release `kps`, namespace `monitoring`),
  ставился Helm 4.3.2.
- Компоненты: Prometheus Operator, Prometheus, Grafana, kube-state-metrics,
  node-exporter. Alertmanager **отключён** (экономия ресурсов), правила алертов
  chart'а отключены (`defaultRules.create: false`) — мы используем только свои
  recording rules.
- Отключены `kubeEtcd`, `kubeControllerManager`, `kubeScheduler`, `kubeProxy`:
  в k3s они работают внутри процесса k3s, отдельных scrape-target'ов нет.
- Prometheus: retention **48h**, scrapeInterval **15s**, включён
  `enableRemoteWriteReceiver` (k6 пишет метрики через remote write),
  PVC 8 GiB на `local-path`.
- Доступ только ClusterIP. Grafana и Prometheus открываются через
  `kubectl port-forward` + SSH-туннель, наружу порты не публикуются.

## Сколько ресурсов потребляет мониторинг

Requests (суммарно ~430m CPU / ~930Mi RAM):

| Компонент | CPU request | RAM request | RAM limit |
|---|---|---|---|
| Prometheus | 250m | 512Mi | 1536Mi |
| Prometheus Operator | 50m | 128Mi | 256Mi |
| Grafana | 50m | 128Mi | 768Mi |
| kube-state-metrics | 50m | 128Mi | 192Mi |
| node-exporter | 30m | 32Mi | 64Mi |

На узле 2 vCPU это заметная доля: системные поды + мониторинг занимают ~780m,
поэтому OCR-подам остаётся ~1.2 CPU. Это напрямую ограничивает `maxReplicas`
(см. `docs/04-calibration.md`).

## Проверка targets

```bash
kubectl -n monitoring port-forward svc/prometheus-operated 19090:9090
curl -s 'http://127.0.0.1:19090/api/v1/targets?state=active' | jq '.data.activeTargets | length'
```

Результат: **11 active targets, все `up`** (`kubelet`, `coredns`, `apiserver`,
`node-exporter`, `kube-state-metrics`, `prometheus`, `operator`, ...).

Проверенные метрики:

- `kube_pod_container_resource_requests`, `kube_pod_container_resource_limits`
- `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`
- `container_cpu_cfs_throttled_periods_total` / `..._periods_total`
- `kube_pod_container_status_restarts_total`
- `kube_pod_container_status_last_terminated_reason`
- `kube_horizontalpodautoscaler_status_{current,desired}_replicas`
- `kube_deployment_status_replicas`
- `kube_pod_status_phase`

## Метрики рекомендаций VPA

kube-state-metrics по умолчанию не отдаёт VPA. Включён
`customResourceState` (формат проверен по документации KSM **v2.20.0**, которая
идёт с chart 9.0.1) и добавлен RBAC `list/watch` на
`autoscaling.k8s.io/verticalpodautoscalers`.

Получились gauge-метрики (значения CPU — в ядрах, память — в байтах):

```
kube_verticalpodautoscaler_status_recommendation_containerrecommendations_target_cpu
kube_verticalpodautoscaler_status_recommendation_containerrecommendations_target_memory
kube_verticalpodautoscaler_status_recommendation_containerrecommendations_lowerbound_cpu
kube_verticalpodautoscaler_status_recommendation_containerrecommendations_lowerbound_memory
kube_verticalpodautoscaler_status_recommendation_containerrecommendations_upperbound_cpu
kube_verticalpodautoscaler_status_recommendation_containerrecommendations_upperbound_memory
```

Проверка (VPA должен уже посчитать рекомендации):

```bash
curl -s 'http://127.0.0.1:19090/api/v1/query?query=kube_verticalpodautoscaler_status_recommendation_containerrecommendations_target_cpu' \
  | jq -r '.data.result[] | "\(.metric.container) cpu=\(.value[1])"'
# ocr cpu=0.5   (0.5 ядра = 500m)
```

Если бы `customResourceState` не заработал, fallback — `scripts/vpa-snapshot.sh`
(сохраняет `kubectl get vpa -o json`), который всё равно вызывается в конце
каждого прогона.

## Доступ

```bash
# Grafana
kubectl -n monitoring port-forward svc/kps-grafana 13000:80
# Prometheus
kubectl -n monitoring port-forward svc/prometheus-operated 19090:9090
```

С ноутбука — через SSH-туннель:

```bash
ssh -L 13000:127.0.0.1:13000 -L 19090:127.0.0.1:19090 ubuntu@<ec2-public-ip>
```

Grafana: `admin` / `ocrlab` (пароль задан в values; только для локального стенда).

Для доступа снаружи (если это осознанно разрешено в security group) форварды
запущены systemd-юнитами `grafana-port-forward` и `prometheus-port-forward`
с `--address 0.0.0.0`; они автоматически переподключаются после рестарта пода.
Порт Grafana: 13000, Prometheus: 19090. `root_url` в values указывает на
публичный адрес, иначе логин редиректит на `localhost:3000`.

> Инцидент: с лимитом памяти 256Mi Grafana 13 периодически падала `OOMKilled`
> и отдавала страницу «Grafana has failed to load its application files».
> Лимит поднят до 768Mi — это обязательный минимум для этого стенда.
