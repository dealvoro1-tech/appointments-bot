FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY appbot ./appbot
# БД лежить у томі /app/data, токен передається через змінні оточення / --env-file
ENV DATABASE_PATH=/app/data/appointments.db
VOLUME ["/app/data"]
CMD ["python", "-m", "appbot"]
