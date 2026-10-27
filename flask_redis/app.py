import time
import socket

from flask import Flask, Response
import redis
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)
cache = redis.Redis(host='redis', port=6379)

# Доп. задание (унаследовано из Lab 08): нативная метрика Prometheus - счётчик посещений сайта.
VIEW_COUNT = Counter(
    'view_count',
    'Общее количество посещений сайта',
    ['service']
)


def get_hit_count():
    retries = 5
    while True:
        try:
            return cache.incr('hits')
        except redis.exceptions.ConnectionError as exc:
            if retries == 0:
                raise exc
            retries -= 1
            time.sleep(0.5)


@app.route('/')
def hello():
    count = get_hit_count()
    VIEW_COUNT.labels(service='Flask-Redis-App').inc()
    # socket.gethostname() в k8s возвращает имя Pod'а - по нему видно,
    # какая именно реплика Deployment'а обработала запрос (демонстрация
    # балансировки нагрузки сервисом LoadBalancer между репликами).
    return (
        f'Привет! Эта страница была просмотрена {count} раз(а).\n'
        f'Запрос обработал Pod: {socket.gethostname()}\n'
        f'Andrey Kosberg — DevOps Course, Lab 09 (Kubernetes).\n'
    )


@app.route('/metrics')
def metrics():
    # Доп. задание: endpoint для нативной выдачи метрик в формате Prometheus.
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
