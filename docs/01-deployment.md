# Stage 1 — базовые манифесты и первый деплой

## Что сделали

1. Расширили корневой диск до 30 GiB. Ubuntu/cloud-init сам расширил раздел,
   `growpart`/`resize2fs` не понадобились: `df -h /` показывает ~28 GiB, свободно ~26 GiB.
2. Установили **k3s `v1.37.2+k3s1`** (Kubernetes v1.37.2), закрепив версию.
   Отключили Traefik и ServiceLB: на 2 vCPU лишние контроллеры только мешают эксперименту.
   `metrics-server` остался (нужен для `kubectl top` и HPA).
3. Создали `env.sh` (параметры узла и образа), `Makefile` и `k8s/base/`.
4. Зафиксировали образ по digest:
   `ferraripupu/ocr-app@sha256:3e1fb257...b1b326`.
5. Применили base, дождались `Ready`, проверили health и реальный OCR-запрос.

## Объекты Kubernetes

| Объект | Файл | Зачем |
|---|---|---|
| `Namespace/ocr-lab` | `k8s/base/namespace.yaml` | изолирует приложение и его ресурсы |
| `Deployment/ocr` | `k8s/base/deployment.yaml` | хранит шаблон пода и следит за числом реплик |
| `Service/ocr` | `k8s/base/service.yaml` | стабильное имя/IP `ocr:8884` внутри кластера |
| `Kustomization` | `k8s/base/kustomization.yaml` | собирает три файла в один `kubectl apply -k` |

Связи: `Service.selector=app:ocr` → находит поды `Deployment` с меткой `app:ocr`
(и только те, что прошли readiness). Deployment создаёт `ReplicaSet`, ReplicaSet — поды.

## Ключевые решения в Deployment

- **digest вместо тега** — один и тот же образ во всех прогонах.
- **requests `cpu: 400m`, `memory: 256Mi`** — откалиброваны на Stage 5
  (`docs/04-calibration.md`). HPA считает утилизацию как `usage / request`,
  поэтому это критично.
- **limits только по памяти `384Mi`** — превышение = `OOMKilled` (рестарт).
  **CPU limit не ставим:** он вызывает CFS-throttling и добавляет разброс в латентность.
- **QoS-класс** при таких настройках — **Burstable** (requests < limits).
  Есть ещё `Guaranteed` (requests == limits) и `BestEffort` (ничего не задано).
- **startupProbe** даёт до 150 с на старт; пока она не прошла, liveness не убивает под.
- **readinessProbe** управляет попаданием в Service (частые проверки, 5 с).
- **livenessProbe** мягкая (10 с, 6 ошибок подряд): под нагрузкой не должно быть
  ложных рестартов.
- `nodeSelector` на единственный узел — чтобы намерение было явным.

## Проверка (что реально получилось)

```bash
make status
kubectl -n ocr-lab get pods -o wide
kubectl describe node | sed -n '/Allocatable:/,/System Info:/p'
```

Факты:

- узел `ip-172-31-4-94`, `Ready`;
- allocatable: **cpu = 2**, **memory = 7961972Ki (~7.59 GiB)**;
- под `ocr-...` — `1/1 Running`, restarts 0;
- `GET /.well-known/health/ready` → `200 {"status":"UP","checks":[]}`;
- `POST /tesseract` с `load/sample.png` → `200`, распознанный текст совпал,
  время одного запроса ≈ 0.56 с.

Пример ручной проверки:

```bash
make pf   # в отдельном терминале
curl -sS -X POST http://127.0.0.1:8884/tesseract \
  -F 'file=@load/sample.png' \
  -F 'options={"languages":["eng"],"pageSegmentationMethod":3}'
```

## Важное ограничение стенда

Вместо `c5.xlarge` доступен только **`m7i-flex.large`: 2 vCPU / 8 GiB**.
Значит:

- `floor(2000m / 400m) = 5` подов — верхняя граница *до* системных подов
  и мониторинга; с мониторингом (780m) помещается ровно **3** пода (1980m / 2000m).
- `maxReplicas` в HPA ограничен 3, иначе поды уйдут в `Pending`.
- Это само по себе результат: на одном узле автоскейлинг упирается в потолок,
  для роста нужен Cluster Autoscaler или несколько узлов.
- k6 работает на том же узле, поэтому конкурирует за CPU с приложением.
  Это искажает латентность; ограничение отражено в `docs/07-results.md`.

## Шпаргалка по командам

```bash
make up        # установить k3s (если нужно) + применить base
make status    # узлы, Deployment, поды, Service
make top       # потребление CPU/RAM
make health    # port-forward + readiness
make logs      # логи OCR
make events    # последние события namespace
make node      # allocatable
make down      # удалить ресурсы (спросит подтверждение)
```
