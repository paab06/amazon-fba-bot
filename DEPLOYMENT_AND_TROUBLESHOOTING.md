# DEPLOYMENT_AND_TROUBLESHOOTING.md

## 🚀 Deployment Guide

### Ambiente Local (Desarrollo)

#### 1. Requisitos Previos
```bash
# Verificar Python versión
python --version  # >= 3.11

# Verificar Docker
docker --version
docker-compose --version
```

#### 2. Setup Inicial

```bash
# Clonar proyecto
git clone <repo-url>
cd amazon-fba-bot

# Crear venv
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o
venv\Scripts\activate     # Windows

# Instalar dependencias
pip install -e .
pip install pytest pytest-asyncio

# Copiar .env template
cp .env.example .env
# Editar .env con credenciales reales
```

#### 3. Iniciar Servicios
```bash
# Terminal 1: Servicios Docker
docker-compose up -d
docker-compose ps  # Verificar que estén UP

# Esperar a que PostgreSQL esté listo (~10 segundos)
docker-compose logs postgres

# Terminal 2: Inicializar DB (cuando Alembic esté implementado)
alembic upgrade head
```

#### 4. Ejecutar Tests
```bash
# Todos los tests
pytest -v

# Con coverage
pytest --cov=src --cov-report=html

# Tests específicos
pytest tests/test_shields.py -v
pytest tests/test_financial_calc.py -v
```

#### 5. Primer Run
```bash
# Asegurase de que hay data/input_sample.csv
ls data/

# Ejecutar pipeline
fba-bot data/input_sample.csv

# O llamando directamente
python -m src.main data/input_sample.csv
```

---

### Ambiente Producción (Docker Compose)

#### 1. Preparar Credenciales
```bash
# Copiar archivo JSON de Google Sheets
mkdir -p credentials
cp ~/Downloads/google_service_account.json credentials/

# Crear .env con valores REALES
cat > .env << 'EOF'
SP_API_REFRESH_TOKEN=your_real_token
SP_API_CLIENT_ID=amzn1.application-oa2-client...
SP_API_CLIENT_SECRET=...
# ... resto de credenciales
DATABASE_URL=postgresql+asyncpg://fba:secure_password@postgres:5432/fba_bot
REDIS_URL=redis://redis:6379/0
EOF

chmod 600 .env  # Secure permissions
```

#### 2. Build Image
```bash
# Crear Dockerfile (si no existe)
cat > Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install -e .

COPY . .

CMD ["fba-bot", "/data/input.csv"]
EOF

# Build
docker build -t amazon-fba-bot:0.1.0 .

# O usar docker-compose
docker-compose build
```

#### 3. Desplegar
```bash
# Actualizar docker-compose.yml para incluir app service
docker-compose up -d

# Logs
docker-compose logs -f app

# Inspeccionar
docker ps
docker exec amazon-fba-bot_app_1 python -m pytest tests/
```

#### 4. Health Check
```bash
# Verificar servicios
docker-compose ps

# Check PostgreSQL
docker exec amazon-fba-bot_postgres_1 \
  psql -U fba -d fba_bot -c "SELECT COUNT(*) FROM results;"

# Check Redis
docker exec amazon-fba-bot_redis_1 redis-cli PING
```

---

### Ambiente Cloud (AWS EC2 / ECS)

#### 1. Opción A: EC2 + Docker Compose
```bash
# SSH a instancia EC2
ssh -i key.pem ubuntu@instance-ip

# Clonar y setup
git clone <repo-url>
cd amazon-fba-bot
cp .env.prod .env
docker-compose -f docker-compose.prod.yml up -d

# Logs
tail -f /var/log/fba-bot/app.log
```

#### 2. Opción B: ECS + ECR
```bash
# Push a ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com

docker tag amazon-fba-bot:0.1.0 <account>.dkr.ecr.us-east-1.amazonaws.com/amazon-fba-bot:0.1.0
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/amazon-fba-bot:0.1.0

# Crear ECS task/service via AWS Console o Terraform
```

#### 3. Opción C: Lambda (Scheduled)
```python
# Adaptar main.py para Lambda handler
import asyncio
from src.main import run_pipeline

def lambda_handler(event, context):
    """CloudWatch Events → Lambda → Pipeline"""
    csv_path = "s3://bucket/input.csv"  # Descargar de S3
    stats = asyncio.run(run_pipeline(csv_path))
    
    # Subir resultados a S3
    # Enviar notificación SNS
    return {"statusCode": 200, "body": stats}
```

---

## 🐛 Troubleshooting

### 1. Error: `PostgreSQL connection refused`

**Síntoma:**
```
asyncpg.exceptions.PostgresError: could not connect to server
```

**Soluciones:**
```bash
# Verificar que está running
docker-compose ps postgres

# Reiniciar
docker-compose restart postgres
docker-compose logs postgres  # Ver logs

# Conexión manual
psql postgresql://fba:secret@localhost:5432/fba_bot

# Comprobar puerto
netstat -tulpn | grep 5432  # Linux
lsof -i :5432  # Mac
```

**Causa común:** PostgreSQL no está completamente listo (tarda ~10s)
**Fix:** Esperar más tiempo antes de ejecutar pipeline

---

### 2. Error: `SPAPIAuthError: 401 Unauthorized`

**Síntoma:**
```
[ERROR] sp_api.auth_failed status=401 error=invalid_grant
```

**Soluciones:**
```bash
# Verificar credenciales en .env
grep SP_API .env

# Re-generar Refresh Token:
# 1. IR a: https://sellingpartner.amazon.com/apps/manage
# 2. Crear nueva LWA authorization
# 3. Copiar refresh_token a .env

# Verificar hora del sistema (SigV4 timestamp-sensitive)
date  # Debe estar sincronizado

# Probar credentials manualmente
python -c "
from src.core.config import settings
print('Client ID:', settings.sp_api_client_id)
print('Seller ID:', settings.sp_api_seller_id)
"
```

---

### 3. Error: `SPAPIRateLimitError: 429 Too Many Requests`

**Síntoma:**
```
[WARNING] rate_limiter.wait operation=searchCatalogItems wait_seconds=10.5
```

**Soluciones:**
```bash
# Aumentar pipeline concurrency delay
# Editar .env:
PIPELINE_CONCURRENCY=5  # Reducir de 10 a 5

# O modificar timeout en config.py
# y ajustar esperas entre requests

# Distribuir en múltiples runs
# En lugar de procesar 1000 productos de una vez:
# Dividir en lotes: 200 productos × 5 runs
```

**Nota:** 429 es NORMAL en SP-API. El rate limiter debería aguantarlo. Si persiste, contactar con Amazon.

---

### 4. Error: `Redis connection timeout`

**Síntoma:**
```
redis.exceptions.ConnectionError: Error 111 connecting to redis
```

**Soluciones:**
```bash
# Verificar Redis
docker-compose ps redis
docker-compose logs redis

# Reiniciar
docker-compose restart redis

# Conexión manual
redis-cli -h localhost -p 6379 PING

# En .env
REDIS_URL=redis://localhost:6379/0  # localhost no funciona en Docker
# Cambiar a:
REDIS_URL=redis://redis:6379/0  # Nombre del servicio Docker
```

---

### 5. Error: `Google Sheets: 403 Forbidden`

**Síntoma:**
```
[ERROR] sheets.auth_failed status=403 permission_denied
```

**Soluciones:**
```bash
# Verificar archivo JSON exists
ls credentials/google_service_account.json

# Verificar permisos
cat credentials/google_service_account.json | grep -o 'service_account.*email.*@'

# Compartir spreadsheet:
# 1. Copiar email de service account del JSON
# 2. Ir a Google Sheet
# 3. Share → Pegar email → Dar permisos Editor

# Verificar GOOGLE_SHEETS_ID
grep GOOGLE_SHEETS_ID .env

# Obtener ID de URL:
# https://docs.google.com/spreadsheets/d/1mABcd1234567890XYZ/edit
#                            ↑ Este es el ID
```

---

### 6. Error: `CSV: column 'ean' not found`

**Síntoma:**
```
[ERROR] ingestor.invalid_csv error=column_not_found expected=ean
```

**Soluciones:**
```bash
# Verificar formato CSV
head -3 data/input.csv

# Debe tener cabecera exacta:
# ean,buy_price
# 5901234123457,12.50

# Fix: Renombrar columnas si es necesario
# O crear CSV nuevo:
cat > data/test.csv << 'EOF'
ean,buy_price
5901234123457,12.50
4006381333931,8.00
EOF

fba-bot data/test.csv
```

---

### 7. Error: `Worker error: Product timeout`

**Síntoma:**
```
[ERROR] worker.timeout worker_id=3 ean=5901234123457 timeout_seconds=30
```

**Soluciones:**
```bash
# Aumentar timeout de worker
# En src/main.py: modificar asyncio.wait_for(timeout=...)

# O reducir concurrencia
PIPELINE_CONCURRENCY=5

# Verificar conectividad a APIs
# ¿Están vivos SP-API, Keepa, Google?

# Logs detallados
# Editar src/core/logger.py: cambiar a DEBUG
python -c "
import os
os.environ['LOG_LEVEL'] = 'DEBUG'
import subprocess
subprocess.run(['fba-bot', 'data/input.csv'])
"
```

---

### 8. Error: `PipelineDropError: All products dropped`

**Síntoma:**
```
[WARNING] stats: 100 processed, 100 dropped, 0 approved
Drops by shield:
  - blacklist: 100
```

**Análisis:**
```bash
# Significa que la mayoría de marcas están en blacklist

# Verificar data/brand_blacklist.json
cat data/brand_blacklist.json | head -20

# Si es incorrecto:
# 1. Actualizar con marcas reales problemáticas
# 2. O vaciar temporalmente para testing:
echo '{"brands": []}' > data/brand_blacklist.json

# Re-ejecutar
fba-bot data/input.csv
```

---

### 9. Error: `asyncio.InvalidStateError: Event loop is closed`

**Síntoma:**
```
RuntimeError: Event loop is closed
```

**Soluciones:**
```bash
# En Windows, Python 3.10+
# Agregar a src/main.py:
import asyncio
if hasattr(asyncio, 'WindowsSelectorEventLoopPolicy'):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Reintentar
fba-bot data/input.csv
```

---

### 10. Error: `ModuleNotFoundError: No module named 'src'`

**Síntoma:**
```
ModuleNotFoundError: No module named 'src'
```

**Soluciones:**
```bash
# Asegurate de instalar en modo editable
pip install -e .

# O agregar a PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# O ejecutar desde raíz
cd /path/to/amazon-fba-bot
python -m src.main data/input.csv
```

---

## 📊 Monitoreo en Producción

### Logs

**Ubicación de Logs:**
```bash
# Docker
docker-compose logs -f app

# Archivo local (si configurado)
tail -f /var/log/fba-bot/app.log

# ELK / CloudWatch (si integrado)
# AWS CloudWatch:
# - Log Group: /aws/ecs/amazon-fba-bot
# - Log Stream: task/pipeline
```

**Eventos importantes a monitorear:**
```json
{
  "event": "pipeline.start",
  "run_id": "20240515T143052_abc123"
}

{
  "event": "pipeline.complete",
  "approved": 1200,
  "dropped": 300,
  "duration_seconds": 765
}

{
  "event": "worker.error",
  "worker_id": 3,
  "ean": "5901234123457",
  "error": "SPAPIServerError"
}
```

### Métricas Recomendadas

| Métrica | Alert Threshold |
|---------|-----------------|
| Approval Rate | < 10% (algo mal) |
| Error Rate | > 5% |
| Pipeline Duration | > 30 minutos |
| Queue Latency | > 5 segundos |
| DB Insert Errors | > 0 |
| Rate Limit (429) Count | > 10 per 100 products |

### Setup Prometheus (Opcional)

```python
# src/api/metrics.py
from prometheus_client import Counter, Gauge, Histogram

products_processed = Counter('products_processed', 'Total processed')
products_approved = Counter('products_approved', 'Total approved')
pipeline_duration = Histogram('pipeline_duration_seconds', 'Pipeline duration')

def expose_metrics():
    """Exponer en /metrics para Prometheus"""
    from prometheus_client import generate_latest
    return generate_latest()
```

---

## 🔄 Mantenimiento Rutinario

### Diariamente
- ✅ Revisar logs de errors
- ✅ Comprobar disponibilidad de APIs externas
- ✅ Verificar libre espacio en BD (PostgreSQL)

### Semanalmente
- ✅ Revisar productos descartados (¿nuevas restricciones?)
- ✅ Actualizar brand_blacklist.json si es necesario
- ✅ Ejecutar `VACUUM ANALYZE` en PostgreSQL
  ```sql
  VACUUM ANALYZE;
  ```

### Mensualmente
- ✅ Refrescar category_sizes.json
  ```bash
  python scripts/refresh_category_sizes.py
  ```
- ✅ Revisar ROI marginal (¿ajustar min_roi_pct?)
- ✅ Archiver logs antiguos

### Trimestralmente
- ✅ Auditar credenciales (Refresh Tokens, API Keys)
- ✅ Revisar cambios en SP-API docs
- ✅ Backup de PostgreSQL
  ```bash
  docker-compose exec postgres \
    pg_dump -U fba -d fba_bot > backup_$(date +%Y%m%d).sql
  ```

---

## 🔐 Seguridad en Producción

### Checklist de Seguridad

- [ ] Variables secretas en `.env` (nunca en git)
- [ ] `.env` añadido a `.gitignore`
- [ ] Permisos de archivo restrictivos: `chmod 600 .env`
- [ ] Usar variables de entorno o AWS Secrets Manager en production
- [ ] Google Sheets credentials en volumen privado
- [ ] PostgreSQL password fuerte (random, 16+ chars)
- [ ] Redis requirepass activado
- [ ] Firewall: solo acceso IP requerido
- [ ] Actualizar dependencias regularmente
- [ ] Revisar logs para intentos de acceso no autorizado

### Ejemplo: AWS Secrets Manager
```python
# src/core/config_aws.py
import boto3

def load_secrets():
    """Cargar credenciales desde AWS Secrets Manager"""
    client = boto3.client('secretsmanager')
    secret = client.get_secret_value(SecretId='amazon-fba-bot/prod')
    return json.loads(secret['SecretString'])

# En Settings:
settings_dict = load_secrets()
```

---

## 📈 Performance Tuning

### 1. Aumentar Concurrencia
```bash
PIPELINE_CONCURRENCY=20  # default: 10
# Trade-off: más rápido, pero más API calls simultáneas
```

### 2. Optimizar Caché Redis
```bash
# Aumentar memoria Redis en docker-compose
redis:
  image: redis:7-alpine
  command: redis-server --maxmemory 512mb
```

### 3. Optimizar DB
```sql
-- Crear índices adicionales
CREATE INDEX idx_results_roi_pct ON results(roi_pct DESC);
CREATE INDEX idx_drops_created_at ON drops(created_at DESC);

-- Analizar plan de queries
EXPLAIN ANALYZE SELECT * FROM results WHERE asin = 'B07...';
```

### 4. Batching de Sheets
```python
# En exporter.py: aumentar _SHEETS_BATCH_SIZE
_SHEETS_BATCH_SIZE = 100  # default: 50
```

### 5. Reducir Latencia de EAN Resolver
```python
# Pre-cargar caché (si datos históricos disponibles)
# En startup: popular Redis con ASINs previos
```

---

## 💡 Tips & Tricks

### Debug rápido
```bash
# Ejecutar con debug mode
DEBUG=1 fba-bot data/input.csv

# O agregar en código
import pdb; pdb.set_trace()
```

### Testing
```bash
# Ejecutar tests con output
pytest tests/ -v -s

# Coverage
pytest --cov=src --cov-report=term-missing

# Test de performance
pytest tests/ --durations=10
```

### Limpieza
```bash
# Borrar datos test
docker-compose exec postgres \
  psql -U fba -d fba_bot -c "DELETE FROM results WHERE created_at < NOW() - INTERVAL '7 days';"

# Limpiar Redis
docker-compose exec redis redis-cli FLUSHDB

# Limpiar logs viejos
find logs -mtime +30 -delete
```

---

**Fin de DEPLOYMENT_AND_TROUBLESHOOTING.md**
