# QUICK_START.md - Guía de Inicio Rápido

## 5 Minutos Para Empezar

### 1️⃣ Prerequisites
```bash
# Verificar versiones
python --version      # >= 3.11
docker --version      # >= 20.0
docker-compose --version  # >= 1.29
```

### 2️⃣ Clone & Setup
```bash
git clone <repo-url>
cd amazon-fba-bot

python -m venv venv
source venv/bin/activate  # Mac/Linux
# o
venv\Scripts\activate     # Windows

pip install -e .
```

### 3️⃣ Configure .env
**Crear archivo `.env` en la raíz:**
```bash
# SP-API (Amazon)
SP_API_REFRESH_TOKEN="YOUR_REFRESH_TOKEN"
SP_API_CLIENT_ID="amzn1.application-oa2-client.xxxxx"
SP_API_CLIENT_SECRET="YOUR_SECRET"
SP_API_SELLER_ID="YOUR_SELLER_ID"

# AWS (para firmar requests)
AWS_ACCESS_KEY_ID="YOUR_ACCESS_KEY"
AWS_SECRET_ACCESS_KEY="YOUR_SECRET_KEY"
AWS_ROLE_ARN="arn:aws:iam::123456789:role/SPAPIRole"

# Keepa
KEEPA_API_KEY="YOUR_KEEPA_KEY"

# Google Sheets
GOOGLE_SHEETS_ID="1mABcd1234567890XYZ"
GOOGLE_CREDENTIALS_JSON_PATH="credentials/google_service_account.json"

# Database (con Docker, estos valores son correctos)
DATABASE_URL="postgresql+asyncpg://fba:secret@postgres:5432/fba_bot"
REDIS_URL="redis://redis:6379/0"

# Pipeline Settings
MIN_ROI_PCT=20.0
BSR_TOP_PCT=2.0
PREP_SHIPPING_FIXED=0.50
PIPELINE_CONCURRENCY=10
```

**Obtener Credenciales:**
- **SP-API**: https://sellingpartner.amazon.com/apps/manage
- **Google Service Account**: https://console.cloud.google.com/iam-admin/serviceaccounts
- **Keepa**: https://keepa.com/#!myKeys

### 4️⃣ Start Services
```bash
# Terminal 1: Servicios
docker-compose up -d

# Verificar
docker-compose ps
# Output esperado:
# postgres    running
# redis       running
```

### 5️⃣ First Run
```bash
# Terminal 2: Ejecutar pipeline
fba-bot data/input_sample.csv

# Output esperado:
# [INFO] pipeline.start run_id=20240515T143052_abc123
# [PROGRESS] Processing 100 products...
# ✓ 80 approved | ✗ 20 dropped | ⚠️ 0 errors
# [INFO] Exported 80 rows to Google Sheets
# [INFO] Exported 80 results to PostgreSQL
# [INFO] pipeline.complete duration_seconds=34.2
```

---

## 📝 Próximos Pasos

### Leer Documentación
- **README.md** - Overview general del proyecto
- **ARCHITECTURE.md** - Arquitectura técnica detallada
- **API_REFERENCE.md** - Documentación de APIs por módulo
- **DEPLOYMENT_AND_TROUBLESHOOTING.md** - Deployment, debugging y mantenimiento

### Customizar CSV de Entrada
```bash
# Ver formato esperado
cat data/input_sample.csv

# Crear tu propio CSV
cat > data/my_input.csv << 'EOF'
ean,buy_price
5901234123457,12.50
4006381333931,8.00
3574660606906,15.99
EOF

# Ejecutar
fba-bot data/my_input.csv
```

### Revisar Resultados
```bash
# Ver logs completos
docker-compose logs app

# Ver resultados en Google Sheets
# Ir a: https://docs.google.com/spreadsheets/d/{GOOGLE_SHEETS_ID}

# Ver datos en PostgreSQL
docker-compose exec postgres psql -U fba -d fba_bot
fba_bot=# SELECT COUNT(*) FROM results;
fba_bot=# SELECT asin, roi_pct, net_profit FROM results LIMIT 10;
fba_bot=# \q
```

### Explorar Código
```bash
# Estructura básica
src/
├── main.py                    # Orquestador principal
├── api/
│   ├── sp_api_client.py      # SP-API (Amazon)
│   └── keepa_client.py       # Keepa API
├── pipeline/
│   ├── ingestor.py           # Lectura CSV
│   ├── ean_resolver.py       # EAN→ASIN
│   ├── shields.py            # Validación 5 escudos
│   ├── financial_calc.py     # ROI/Rentabilidad
│   └── exporter.py           # Google Sheets + DB
└── core/
    ├── config.py             # Configuración
    ├── rate_limiter.py       # Control de throttling
    ├── logger.py             # Logging
    └── exceptions.py         # Excepciones custom

# Ejecutar tests
pytest tests/ -v
```

---

## 🆘 Problemas Comunes

| Problema | Solución |
|----------|----------|
| `PostgreSQL connection refused` | `docker-compose restart postgres` |
| `SPAPIAuthError: 401` | Verificar credenciales en .env |
| `Google Sheets: 403` | Compartir sheet con email de Google SA |
| `Redis connection timeout` | `docker-compose restart redis` |
| `No module named 'src'` | `pip install -e .` |
| `429 Too Many Requests` | Reducir `PIPELINE_CONCURRENCY=5` |

👉 Ver **DEPLOYMENT_AND_TROUBLESHOOTING.md** para troubleshooting completo.

---

## 📊 Workflow Típico

```
1. CSV Input
   └─ data/input_sample.csv

2. Run Pipeline
   └─ fba-bot data/input_sample.csv

3. Monitor
   ├─ Logs: docker-compose logs -f app
   ├─ Google Sheets: Check new rows
   └─ PostgreSQL: Query results table

4. Analyze
   ├─ What ROI did we get?
   ├─ Which products were dropped? Why?
   ├─ Any errors to debug?

5. Iterate
   ├─ Adjust min_roi_pct if needed
   ├─ Update brand_blacklist.json
   └─ Re-run with improved criteria
```

---

## 🔗 Recursos Útiles

**Documentación Externa:**
- [SP-API Docs](https://developer-docs.amazon.com/sp-api/)
- [Keepa API](https://keepa.com/raw_csv_download.html)
- [Google Sheets API](https://developers.google.com/sheets/api)
- [asyncpg Docs](https://magicstack.github.io/asyncpg/)

**Herramientas Recomendadas:**
- **pgAdmin** - GUI para PostgreSQL
  ```bash
  docker run -p 80:80 \
    -e PGADMIN_DEFAULT_EMAIL=admin@admin.com \
    -e PGADMIN_DEFAULT_PASSWORD=admin \
    dpage/pgadmin4
  # Acceder a localhost:80
  ```

- **Redis Commander** - GUI para Redis
  ```bash
  npm install -g redis-commander
  redis-commander -h localhost -p 6379
  ```

- **Postman** - Test SP-API requests
- **VSCode Extension:** Python, Pylance, Docker

---

## 💬 FAQ

### ¿Cuánto tiempo tarda un run típico?
- 100 productos: ~5 minutos
- 1000 productos: ~45 minutos
- 10000 productos: ~6-8 horas (con PIPELINE_CONCURRENCY=10)

### ¿Cuál es el máximo de productos por run?
Sin límite técnico. Solo limitado por:
- Tiempo disponible
- Cuotas de API (SP-API, Keepa)
- Espacio en BD

### ¿Se pueden ejecutar múltiples runs en paralelo?
No recomendado. Comparten:
- Redis caché
- PostgreSQL connections
- Rate limits de APIs

Mejor: ejecutar runs secuencialmente.

### ¿Qué pasa si un producto falla?
- Se descarta con motivo logged
- El pipeline NO se para
- Se registra en tabla `errors` o `drops`
- Puedes revisar luego los logs

### ¿Cómo actualizar datos históricos (category sizes)?
```bash
python scripts/refresh_category_sizes.py
# Script actualiza data/category_sizes.json
# Ejecutar trimestralmente
```

### ¿Cómo exportar resultados fuera de Google Sheets?
```bash
# PostgreSQL → CSV
docker-compose exec postgres psql -U fba -d fba_bot \
  -c "COPY results TO STDOUT WITH CSV HEADER" > results.csv

# Luego abrir en Excel, Google Sheets, etc
```

---

## 🎯 Next Steps Recomendados

**Corto Plazo (Hoy):**
1. ✅ Seguir Quick Start
2. ✅ Ejecutar con datos de prueba
3. ✅ Revisar output en Google Sheets

**Mediano Plazo (Esta semana):**
1. 📖 Leer ARCHITECTURE.md completo
2. 🧪 Ejecutar tests (`pytest tests/`)
3. 🔍 Explorar código de shields y calculator
4. ⚙️ Customizar criterios (ROI, BSR top%)

**Largo Plazo (Este mes):**
1. 🚀 Desplegar en producción (Docker/AWS)
2. 📊 Implementar dashboard con resultados
3. 🔄 Automatizar runs diarios (Cron/Lambda)
4. 📈 Monitoreo con Prometheus/Grafana
5. 🤖 Integrar con sistema de reprecio

---

## 📞 Support & Contribution

**Problemas o preguntas:**
- Revisar DEPLOYMENT_AND_TROUBLESHOOTING.md
- Revisar logs: `docker-compose logs -f app`
- Contactar al equipo de desarrollo

**Contribuciones:**
- Fork del repositorio
- Crear feature branch
- Enviar PR

---

**¡Listo para empezar! 🚀**

Cualquier pregunta, revisar los docs o contactar al equipo.
