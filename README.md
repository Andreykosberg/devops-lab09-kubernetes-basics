# DevOps Lab 09 — Kubernetes basics (minikube)

Andrey Kosberg — DevOps Course, Lab 09: «Куберизация» Flask+Redis приложения из Lab 08 — развёртывание в одно-узловом кластере Kubernetes (minikube).

Все команды ниже выполнены **по-настоящему** на виртуальной машине `devops-lab01` (тот же стенд, что в Lab 01-08), через SSH (`andrey@127.0.0.1:2223`). Перед началом лабораторной ресурсы VM были увеличены с хост-машины через VirtualBox (`VBoxManage modifyvm`), как того явно требует задание («Предварительно увеличиваем ресурсы vm»).

## Стенд

| | |
|---|---|
| VM | devops-lab01 (Ubuntu 24.04 noble, тот же стенд, что в Lab 01-08) |
| RAM | увеличена с 2048 МБ до **4096 МБ** (`VBoxManage modifyvm devops-lab01 --memory 4096 --cpus 2`), VM перезагружена |
| CPU | 2 ядра |
| IP VM внутри NAT | `10.0.2.15` |
| Docker | 29.1.3 (установлен в Lab 07) |
| kubectl | v1.37.1 |
| minikube | v1.39.0, драйвер `docker` (вложенная виртуализация: VM → docker-контейнер `minikube` → поды k8s внутри него) |
| k8s (внутри minikube) | v1.37.0, containerd 2.3.4 |
| Ресурсы minikube | `--cpus=2 --memory=3000mb` (явно ограничено под RAM VM; оставлен запас ~800 МБ для ОС и 7 контейнеров Lab 07/08, которые продолжают работать рядом, не тронуты) |

## Содержимое репозитория

```
devops-lab09-kubernetes-basics/
├── flask_redis/                 # приложение, версия v1 (образ flask:v1)
│   ├── app.py                   # Flask + Redis + socket.gethostname() + /metrics (доп.задание)
│   ├── Dockerfile
│   └── requirements.txt
├── flask_redis_v2/               # приложение, версия v2 (для демонстрации RollingUpdate)
│   ├── app.py                   # тот же код, другой текст ответа ("Hello World VERSION 2!")
│   ├── Dockerfile
│   └── requirements.txt
├── flask_redis_k8s/              # манифесты Kubernetes
│   ├── flask.yml                # Deployment flask-app, 3 реплики
│   ├── flask-service.yml        # Service service-devops, type LoadBalancer
│   ├── redis.yml                # Deployment redis, 1 реплика
│   └── redis-service.yml        # Service redis, type ClusterIP
├── screenshots/                  # 7 скриншотов реального выполнения
└── README.md
```

## Задание и как оно выполнено

Лекция и практика Л09/П09 "Kubernetes basics". Основное (и единственное практическое) задание (слайд 23):

> Задача: «Куберизировать» приложение Flask+Redis из предыдущей практики и обновить
> 1. Разворачиваем на vm мини-кластер k8s - minikube (Предварительно увеличиваем ресурсы vm)
> 2. (опционально: Подключаемся к кластеру с хостовой машины через приложение Lens)
> 3. Собираем образы будущих контейнеров и прокидываем их внутрь minikube
> 4. Создаем манифесты – описания приложений и сервисов
> 5. Разворачиваем deployment/ReplicaSet с application-серверами и БД и сервисы
> 6. Активируем балансировщик входящих запросов (служба LoadBalancer)
> 7. Проверяем работу сервисов
> 8. Обновляем веб сервисы на новую версию (RollingUpdate)

Все 8 пунктов выполнены (кроме п.2 — опциональное подключение GUI Lens с хоста, явно помечено в лекции как необязательное, пропущено). Ниже — по шагам, с реальными командами и результатами.

### 1. Увеличение ресурсов VM

minikube рекомендует 2 CPU / 4 ГБ RAM. У `devops-lab01` было только 1.9 ГиБ RAM — увеличено с хост-машины:

```bash
VBoxManage modifyvm devops-lab01 --memory 4096 --cpus 2   # VM предварительно выключена (shutdown -h now)
VBoxManage startvm devops-lab01 --type headless
```

После перезагрузки: `free -h` → ~3.8 ГиБ, `nproc` → 2. Все 7 контейнеров Lab 07/08 поднялись автоматически (`restart: unless-stopped` / `always`), ничего не потеряно.

### 2. Установка kubectl и minikube

```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube_latest_amd64.deb
sudo dpkg -i minikube_latest_amd64.deb
```

`kubectl version --client` → v1.37.1, `minikube version` → v1.39.0. Пользователь `andrey` уже был в группе `docker` (с Lab 07), swap выключен (`swapon --show` — пусто) — отдельная настройка не потребовалась.

### 3. Запуск кластера

```bash
minikube start --vm-driver=docker --cpus=2 --memory=3000mb
```

Реальный результат (~340 с, скачивание preload-образа k8s v1.37.0):

```
* Done! kubectl is now configured to use "minikube" cluster and "default" namespace by default
```

Проверка здоровья кластера — всё по методичке:

```bash
$ minikube status
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured

$ kubectl get nodes
NAME       STATUS   ROLES           VERSION
minikube   Ready    control-plane   v1.37.0

$ kubectl get services
NAME         TYPE        CLUSTER-IP   PORT(S)
kubernetes   ClusterIP   10.96.0.1    443/TCP
```

### 4. Сборка и загрузка образов внутрь minikube

Приложение — модифицированная версия Flask+Redis из Lab 08: добавлен `import socket` и `socket.gethostname()` в тело ответа, чтобы видеть, какой именно Pod/реплика обработали запрос (остальное — счётчик в Redis и `/metrics` с доп.заданием Lab 08 — сохранено без изменений):

```python
@app.route('/')
def hello():
    count = get_hit_count()
    VIEW_COUNT.labels(service='Flask-Redis-App').inc()
    return (
        f'Привет! Эта страница была просмотрена {count} раз(а).\n'
        f'Запрос обработал Pod: {socket.gethostname()}\n'
        f'Andrey Kosberg — DevOps Course, Lab 09 (Kubernetes).\n'
    )
```

Сборка образа **прямо внутрь minikube** (без push в внешний registry) и загрузка `redis:alpine`:

```bash
$ minikube image build -t flask:v1 flask_redis/
...
#10 naming to docker.io/library/flask:v1 done

$ minikube image load redis:alpine

$ minikube image ls | grep -E 'flask|redis'
docker.io/library/redis:alpine
docker.io/library/flask:v1
```

### 5. Манифесты

`flask_redis_k8s/flask.yml` — Deployment, 3 реплики (в лекции 5, уменьшено до 3 под ограниченные ресурсы VM/minikube, 256Mi лимит на под):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flask-app
  labels:
    app: flask-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: flask-app
      svc: front
  template:
    metadata:
      labels:
        app: flask-app
        svc: front
    spec:
      containers:
      - name: flask
        image: flask:v1
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 5000
        resources:
          limits:
            memory: "256Mi"
```

`flask_redis_k8s/flask-service.yml` — Service типа **LoadBalancer** (externalIPs = адрес VM в NAT-сети, `10.0.2.15`; порт **8001**, а не 8000 из примера лекции — см. «Нюансы» ниже, почему):

```yaml
apiVersion: v1
kind: Service
metadata:
  name: service-devops
  labels:
    app: flask-app
spec:
  type: LoadBalancer
  selector:
    app: flask-app
    svc: front
  ports:
  - port: 8001
    targetPort: 5000
  externalIPs:
  - 10.0.2.15
```

`flask_redis_k8s/redis.yml` (Deployment, 1 реплика) и `flask_redis_k8s/redis-service.yml` (Service типа **ClusterIP**, только для внутреннего обращения `flask` → `redis` по DNS-имени `redis`) — взяты из методички без изменений (см. файлы в репозитории).

### 6-7. Развёртывание и реальная проверка работы

```bash
$ kubectl apply -f flask_redis_k8s/
service/service-devops created
deployment.apps/flask-app created
service/redis created
deployment.apps/redis created

$ kubectl get pods -o wide
NAME                         READY   STATUS    RESTARTS   AGE
flask-app-7cd68d696f-4zg9s   1/1     Running   0          10s
flask-app-7cd68d696f-6mhnt   1/1     Running   0          10s
flask-app-7cd68d696f-x9f8n   1/1     Running   0          10s
redis-587784b748-l6vd7       1/1     Running   0          10s

$ kubectl get services -o wide
NAME             TYPE           CLUSTER-IP       EXTERNAL-IP   PORT(S)
redis            ClusterIP      10.98.254.229    <none>        6379/TCP
service-devops   LoadBalancer   10.111.246.159   10.0.2.15     8001:31854/TCP
```

Т.к. minikube с драйвером `docker` сам работает внутри docker-контейнера (вложенная виртуализация), для реального доступа к LoadBalancer-сервису снаружи понадобился `minikube tunnel`, причём именно с флагом `--bind-address`, указывающим на собственный IP VM в NAT-сети (без этого флага `curl` к `10.0.2.15:8001` отдавал `Connection refused` — tunnel по умолчанию прокладывает маршрут только для CIDR ClusterIP-адресов, 10.96.0.0/12, но не для адреса самого узла):

```bash
sudo minikube tunnel --bind-address 10.0.2.15 &
```

```
* Tunnel successfully started
* Starting tunnel for service service-devops.
```

Реальная многократная проверка — счётчик (общий, хранится в Redis) растёт монотонно, а Pod, обработавший запрос, меняется между всеми 3 репликами — наглядная демонстрация работы LoadBalancer:

```bash
$ curl -s http://10.0.2.15:8001/
Привет! Эта страница была просмотрена 14 раз(а).
Запрос обработал Pod: flask-app-7cd68d696f-4zg9s

$ curl -s http://10.0.2.15:8001/
Привет! Эта страница была просмотрена 15 раз(а).
Запрос обработал Pod: flask-app-7cd68d696f-x9f8n

$ curl -s http://10.0.2.15:8001/
Привет! Эта страница была просмотрена 16 раз(а).
Запрос обработал Pod: flask-app-7cd68d696f-6mhnt
```

За 10 подряд запросов засветились все 3 Pod'а (`4zg9s`, `x9f8n`, `6mhnt`), счётчик монотонно вырос с 14 до 23. `/metrics` (доп.задание из Lab 08) тоже работает через сервис:

```bash
$ curl -s http://10.0.2.15:8001/metrics | grep view_count_total
view_count_total{service="Flask-Redis-App"} 8.0
```

### 8. RollingUpdate — обновление на новую версию

Изменён текст ответа в `flask_redis_v2/app.py` (остальной код идентичен) — собран новый образ и применено обновление **живого** Deployment'а:

```bash
$ minikube image build -t flask:v2 flask_redis_v2/
...
#10 naming to docker.io/library/flask:v2 done

$ curl -s http://10.0.2.15:8001/        # ДО обновления
Привет! Эта страница была просмотрена 24 раз(а).
Запрос обработал Pod: flask-app-7cd68d696f-4zg9s

$ kubectl set image deployment/flask-app flask=flask:v2
deployment.apps/flask-app image updated
```

Переходный процесс зафиксирован вживую (`kubectl get pods -o wide` каждые ~2-3 с): сначала 3 старых пода Running + 1 новый ContainerCreating, затем старые один за другим переходят в Terminating по мере готовности новых — классический rolling surge:

```
flask-app-7cd68d696f-4zg9s   1/1   Running             0   12m
flask-app-7cd68d696f-6mhnt   1/1   Running             0   12m
flask-app-7cd68d696f-x9f8n   1/1   Running             0   12m
flask-app-9f945fd44-9ztgf    0/1   ContainerCreating   0   0s
```

```bash
$ kubectl rollout status deployment/flask-app
deployment "flask-app" successfully rolled out
```

`kubectl describe deployment flask-app` подтверждает итог документально — старый ReplicaSet опущен до 0, новый поднят до 3, и в `Events` видна пошаговая постепенная замена (а не мгновенная «взрыв-замена»):

```
OldReplicaSets:  flask-app-7cd68d696f (0/0 replicas created)
NewReplicaSet:   flask-app-9f945fd44 (3/3 replicas created)
Events:
  Normal  ScalingReplicaSet  Scaled up replica set flask-app-9f945fd44 from 0 to 1
  Normal  ScalingReplicaSet  Scaled down replica set flask-app-7cd68d696f from 3 to 2
  Normal  ScalingReplicaSet  Scaled up replica set flask-app-9f945fd44 from 1 to 2
  Normal  ScalingReplicaSet  Scaled down replica set flask-app-7cd68d696f from 2 to 1
  Normal  ScalingReplicaSet  Scaled up replica set flask-app-9f945fd44 from 2 to 3
  Normal  ScalingReplicaSet  Scaled down replica set flask-app-7cd68d696f from 1 to 0
```

Финальная проверка — все поды новые, ответ приложения изменился:

```bash
$ kubectl get pods -o wide
flask-app-9f945fd44-2cmpj   1/1   Running   0   26s
flask-app-9f945fd44-9ztgf   1/1   Running   0   27s
flask-app-9f945fd44-flxsp   1/1   Running   0   25s

$ curl -s http://10.0.2.15:8001/
Hello World VERSION 2! Эта страница была просмотрена 25 раз(а).
Запрос обработал Pod: flask-app-9f945fd44-2cmpj
```

Счётчик продолжился с того же значения (25, а не сброшен) — подтверждение, что Redis (отдельный под, не пересоздавался при обновлении `flask-app`) пережил RollingUpdate приложения без потерь данных.

## Нюансы и наблюдения

- **Увеличение ресурсов VM обязательно с хоста.** minikube настойчиво предупреждает о недостатке памяти (`"does not leave room for system overhead"`) даже при `--memory=3000mb` на VM с 4 ГБ RAM, если не увеличить саму VM заранее — поэтому первым шагом сделан `VBoxManage modifyvm` с хост-машины (VM предварительно выключена через `sudo shutdown -h now`, затем перезапущена `VBoxManage startvm --type headless`).
- **Порт сервиса изменён с 8000 (как в примере лекции) на 8001.** На `devops-lab01` порт 8000 уже занят контейнером `flask-redis-web-1` из Lab 08 (`docker-proxy`, `docker compose up -d` оставлен работающим намеренно, чтобы не ломать предыдущую лабораторную) — при попытке повесить k8s `externalIPs: [10.0.2.15]` на тот же порт 8000 возник бы конфликт на уровне iptables NAT. Решение — простое смещение порта в манифесте `flask-service.yml`, без изменения архитектуры.
- **`minikube tunnel` без `--bind-address` не работает с `externalIPs`.** Первая попытка (`sudo minikube tunnel` без флага) оставляла `curl http://10.0.2.15:8001/` с `Connection refused`, хотя сам tunnel-процесс запускался без ошибок. Диагностика (`ip route`, `iptables -t nat -L`) показала: без флага tunnel прокладывает маршрут только для CIDR `10.96.0.0/12` (ClusterIP-диапазон), но не создаёт обработку для адреса самого узла VM. Лекция (слайд 46) как раз и предписывает именно `minikube tunnel --bind-address 10.0.2.15` — после перезапуска с этим флагом всё заработало.
- **Кол-во реплик flask-app уменьшено с 5 (в примере лекции) до 3** — под ограниченный бюджет minikube (`--memory=3000mb` на 4 ГБ VM, где уже работают 7 контейнеров Lab 07/08). Балансировка между репликами при этом демонстрируется так же наглядно.
- **Lab 07/08 не пострадали**: все 7 старых контейнеров (nginx×2, flask-redis×2, prometheus, grafana, blackbox) продолжали работать на той же VM всё время выполнения Lab 09, включая момент увеличения RAM/перезагрузки VM (они подняты заново автоматически после ребута и подтверждены `docker ps` на каждом шаге).
- **Опциональный пункт 2 (Lens с хоста) пропущен** — явно помечен в лекции как необязательный; достаточно `kubectl`/`minikube` CLI на самой VM для выполнения и проверки всех обязательных пунктов задания.

## Скриншоты

Все скриншоты в папке `screenshots/` — рендер РЕАЛЬНОГО вывода команд, полученного по SSH:

1. `01-vm-resize-kubectl-minikube-install.png` — увеличение ресурсов VM (VBoxManage с хоста) + установка kubectl/minikube
2. `02-minikube-start-cluster-ready.png` — `minikube start`, кластер Ready, старые контейнеры Lab07/08 не задеты
3. `03-minikube-image-build-load.png` — структура проекта + `minikube image build`/`load` (flask:v1, redis:alpine)
4. `04-kubectl-apply-pods-services.png` — `kubectl apply -f`, поды Running, сервисы (в т.ч. LoadBalancer) созданы
5. `05-loadbalancer-tunnel-verify.png` — `minikube tunnel` + реальная балансировка между 3 репликами
6. `06-rolling-update-trigger-transition.png` — запуск RollingUpdate (`kubectl set image`) + переходный процесс
7. `07-rolling-update-events-final.png` — `describe deployment` (Events) + финал: все поды на flask:v2
