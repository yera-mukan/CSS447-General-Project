# Stage 2 — установка Vertical Pod Autoscaler (VPA)

## Версия и совместимость

- Установлен **VPA `1.8.1`** (последний стабильный на момент работы, октябрь 2026)
  из официального репозитория `kubernetes/autoscaler`, тег `vertical-pod-autoscaler-1.8.1`.
- Кластер: **k3s `v1.37.2+k3s1` (Kubernetes 1.37.2)**.
- Образы закреплены тегом `1.8.1`:
  `registry.k8s.io/autoscaling/vpa-{recommender,updater,admission-controller}:1.8.1`.
- VPA 1.8.1 — актуальная ветка, поддерживает Kubernetes 1.33+ (в т.ч. встроенный
  `InPlacePodVerticalScaling`), поэтому с 1.37 совместим. Версия проверена по
  `docs/features.md` в исходниках релиза.

Установка выполнялась официальным скриптом:

```bash
git clone --depth 1 --branch vertical-pod-autoscaler-1.8.1 \
  https://github.com/kubernetes/autoscaler.git
cd autoscaler/vertical-pod-autoscaler
bash hack/vpa-up.sh          # БЕЗ аргумента "apply": скрипт сам его добавляет
```

> Тонкость: `vpa-up.sh apply` ошибочно трактует `apply` как имя компонента.
> Правильно — просто `bash hack/vpa-up.sh`.

Скрипт сгенерировал TLS-сертификаты для webhook через `openssl` и создал объекты
в namespace `kube-system`.

## Какие объекты появились

| Объект | Роль |
|---|---|
| `CRD verticalpodautoscalers.autoscaling.k8s.io` | сам объект VPA (`apiVersion: autoscaling.k8s.io/v1`) |
| `CRD verticalpodautoscalercheckpoints...` | история рекомендаций (checkpoints) |
| `Deployment/vpa-recommender` | смотрит на потребление и считает `lowerBound / target / upperBound` |
| `Deployment/vpa-updater` | вытесняет поды, если их requests вне рекомендаций |
| `Deployment/vpa-admission-controller` | при создании пода подставляет рекомендованные requests |
| `Service/vpa-webhook` + Secret | MutatingWebhook, через который работает admission-controller |
| RBAC (ClusterRole/Binding) | доступ компонентов к метрикам, подам, VPA-объектам |

Проверка:

```bash
kubectl get crd | grep verticalpodautoscaler
kubectl -n kube-system get pods | grep vpa
kubectl -n kube-system logs deploy/vpa-recommender --tail=20
```

Все три пода — `Running`.

## Режимы `updateMode` в установленной версии

`kubectl explain verticalpodautoscalers.autoscaling.k8s.io.spec.updatePolicy.updateMode`
показывает:

| Режим | Что делает |
|---|---|
| `Off` | только рекомендации, ничего не меняет (сценарий E) |
| `Initial` | задаёт requests только при создании пода, потом не трогает |
| `Recreate` | задаёт при создании и вытесняет/пересоздаёт под при выходе за границы |
| `Auto` | **устарел с VPA 1.5**, сейчас эквивалентен `Recreate` |
| `InPlaceOrRecreate` | сначала пробует изменить ресурсы «на месте», иначе пересоздаёт |
| `InPlace` | только in-place, никогда не вытесняет (alpha-флаг) |

Мы используем **`Recreate`** вместо устаревшего `Auto`: поведение то же, но без
предупреждений. В сценарии C каталог по-прежнему называется `C-vpa-auto`.

## Поведение updater при `replicas: 1`

По умолчанию у updater `--min-replicas=2` (`pkg/updater/config/config.go`).
Это значит: **единственный под workload'а он не вытесняет**, чтобы не уронить сервис.
Обойти можно двумя способами:

1. Держать `replicas: 2` — так сделан сценарий C: один под обновляется, второй
   продолжает принимать трафик.
2. Явно указать в VPA `spec.updatePolicy.minReplicas: 1` — тогда updater может
   вытеснить и единственный под (риск краткого простоя). В сценариях не используем,
   но знание важно для понимания.

Дополнительно updater учитывает `eviction-tolerance` (по умолчанию 0.5): за один
проход можно вытеснить не более половины реплик.

## Как посмотреть рекомендации

```bash
kubectl -n ocr-lab describe vpa ocr
kubectl -n ocr-lab get vpa ocr -o jsonpath='{.status.recommendation}' | jq
```

В `status.recommendation.containerRecommendations[]` для контейнера `ocr` будут
`lowerBound`, `target`, `upperBound` по CPU и памяти. Пока VPA не набрал статистику
(обычно несколько минут), `status` пустой.
