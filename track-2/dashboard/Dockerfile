# Dashboard: build data.json from the prepped tables, then serve the page on :3000.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY dashboard/ ./dashboard/
COPY analysis/ ./analysis/
EXPOSE 3000
# The API is optional: build.py falls back to the local tables if it is down.
CMD ["sh", "-c", "python dashboard/build.py && cd dashboard && python -m http.server 3000 --bind 0.0.0.0"]
