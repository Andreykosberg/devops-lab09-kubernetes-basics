FROM python:3.10-alpine

WORKDIR /code

# requirements.txt копируем отдельно от app.py, чтобы слой с зависимостями
# кэшировался и не пересобирался при каждом изменении кода приложения.
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py app.py

EXPOSE 5000

CMD ["python", "app.py"]
