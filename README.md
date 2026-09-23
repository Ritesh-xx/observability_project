# Observability Lab

A small production-style observability practice project:

```text
                   Flask API
                       |
          +------------+------------+
          |            |            |
       Postgres      Redis     External API
          |
          +------------+------------+
                       |
                 Docker network
                       |
                 Prometheus
                       |
                    Grafana
```

## Start

```bash
docker compose up -d --build
```

Check services:

```bash
docker compose ps
```

Open:

- Flask API: http://localhost:8000
- Metrics: http://localhost:8000/metrics
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000

Grafana login: `admin` / `admin`

## Validate Prometheus config

```bash
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose exec prometheus promtool check rules /etc/prometheus/alerts.yml
```

## Learning exercises

### 1. Process dies

```bash
docker compose stop app
```

Observe `up{job="app"}` and the `AppDown` alert. Then:

```bash
docker compose start app
```

### 2. HTTP 500 errors

```bash
for i in $(seq 1 20); do curl -s http://localhost:8000/error >/dev/null; done
```

Query:

```promql
rate(app_http_requests_total{status=~"5.."}[5m])
```

### 3. High latency

```bash
curl "http://localhost:8000/work?delay=2"
```

For continuous traffic, repeat the request in a loop.

### 4. Database failure

```bash
docker compose stop db
curl -i http://localhost:8000/users
```

Observe application errors and logs. Then:

```bash
docker compose start db
```

### 5. Slow database

```bash
curl "http://localhost:8000/db-slow?seconds=5"
```

### 6. Redis failure

```bash
docker compose stop redis
curl -i http://localhost:8000/cache/test
```

Then:

```bash
docker compose start redis
```

### 7. External API failure

Change the external service configuration temporarily by editing `docker-compose.yml` and setting:

```yaml
EXTERNAL_STATUS: 500
```

or make it slow:

```yaml
EXTERNAL_DELAY: 5
```

For a simpler immediate exercise, stop the external service:

```bash
docker compose stop external-api
curl -i http://localhost:8000/external
```

Then restart it.

### 8. CPU saturation

Run:

```bash
curl "http://localhost:8000/cpu?seconds=20"
```

For real CPU saturation, run multiple requests concurrently.

### 9. Memory pressure

Run:

```bash
curl "http://localhost:8000/memory?mb=300&seconds=60"
```

Use moderate values first.
