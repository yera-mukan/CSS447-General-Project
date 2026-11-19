# Stage 3 — сценарии A–E (kustomize overlays)

Все сценарии — это overlay над `k8s/base`. Запуск одного сценария:

```bash
kubectl apply -k k8s/scenarios/<name>
```

## Сводная таблица

| Сценарий | Реплики | HPA | VPA | Идея |
|---|---|---|---|---|
| `A-fixed` | 3 | нет | нет | baseline без автоскейлинга |
| `B-hpa-30` | 1..3 | CPU 30% | нет | агрессивный HPA |
| `B-hpa-50` | 1..3 | CPU 50% | нет | средний HPA |
| `B-hpa-70` | 1..3 | CPU 70% | нет | консервативный HPA |
| `C-vpa-auto` | 2 фикс. | нет | CPU+RAM, `Recreate` | VPA сам подбирает requests/limits |
| `D-hpa-cpu-vpa-mem` | 1..3 | CPU 50% | только RAM | HPA по CPU + VPA по памяти |
| `E-vpa-off` | 1 фикс. | нет | CPU+RAM, `Off` | только рекомендации |

## Как работает HPA

HPA каждые ~15 с сравнивает **среднее потребление CPU** подов с `target utilization`
и меняет число реплик:

```
desiredReplicas = ceil(currentReplicas * currentUtilization / targetUtilization)
```

`utilization` — это **не проценты ядра**, а `usage / requests` контейнера.
Если requests занижены, утилизация выглядит огромной и HPA масштабируется раньше.
Поэтому Stage 5 (калибровка requests) обязателен.

В сценариях B `behavior` одинаковый (сравнение честное):

- `scaleUp.stabilizationWindowSeconds: 0` — реакция на пик сразу;
- `scaleDown.stabilizationWindowSeconds: 120` — не «дёргаем» реплики вниз 2 минуты
  (stabilization window — окно, в течение которого HPA берёт максимум из прошлых
  рекомендаций, чтобы избежать флаппинга).

### Почему `maxReplicas` маленький

Узел один, allocatable **2 vCPU**. С учётом системных подов и мониторинга
(их requests тоже занимают место) при `requests.cpu=400m` реально помещается
ровно 3 пода OCR (1980m из 2000m). Поэтому в overlays стоит `maxReplicas: 3`, а не 6.
Если поставить 6, лишние поды уйдут в `Pending` — это не ошибка стенда,
а демонстрация потолка одного узла: для настоящего масштабирования нужен
Cluster Autoscaler/Karpenter или несколько узлов. Число Pending-подов
выводится на дашборд.

## Как работает VPA

VPA смотрит историю потребления (CPU/RAM) и выдаёт три границы:

- `lowerBound` — минимум, ниже которого нет смысла опускаться;
- `target` — рекомендуемый request;
- `upperBound` — максимум, выше которого request не поднимают.

В режиме `Recreate` admission-controller подставляет `target` новым подам, а updater
вытесняет поды, чьи requests вышли за границы. В `Off` (сценарий E) VPA только
считает рекомендации.

## Почему в сценарии D HPA и VPA не управляют одним ресурсом

- HPA смотрит на **CPU-утилизацию = usage / cpu_request**.
- VPA, если бы управлял CPU, менял бы `cpu_request`.
- Получается замкнутый контур: VPA поднял request → утилизация упала → HPA уменьшил
  реплики → нагрузка на под выросла → VPA снова меняет request. Система «борется
  сама с собой», результаты невоспроизводимы.
- Поэтому в D: **HPA — CPU, VPA — только memory** (`controlledResources: ["memory"]`).
  Разделение ресурсов — стандартная рекомендация.

## Проверка overlays без применения

```bash
kubectl kustomize k8s/scenarios/B-hpa-50
kubectl diff -k k8s/scenarios/C-vpa-auto
```

## Применение и наблюдение

```bash
kubectl apply -k k8s/scenarios/B-hpa-50
kubectl -n ocr-lab get hpa ocr -w
kubectl -n ocr-lab get vpa ocr -w
kubectl -n ocr-lab get pods -o wide
kubectl -n ocr-lab describe vpa ocr
```

Перед сменой сценария обязательно удалить автоскейлеры прошлого (см. `scripts/reset.sh`
на Stage 9): HPA и VPA не должны сосуществовать там, где не задумано.

> Значения `replicas` для A (3) и `maxReplicas` для B/D (3) уже пересчитаны
> после Stage 5 под requests 400m; больше трёх подов на этот узел не помещается.
