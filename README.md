# Amazon FBA Bot - Documentación Técnica Completa

## 📋 Tabla de Contenidos
1. [Descripción General](#descripción-general)
2. [Flujo de Funcionamiento](#flujo-de-funcionamiento)
3. [Arquitectura](#arquitectura)
4. [Componentes Principales](#componentes-principales)
5. [APIs Integradas](#apis-integradas)
6. [Base de Datos](#base-de-datos)
7. [Configuración](#configuración)
8. [Instalación y Ejecución](#instalación-y-ejecución)
9. [Scrapers y Monitores](#scrapers-y-monitores)
10. [Webhooks y Alertas](#webhooks-y-alertas)

---

## 🎯 Descripción General

**Amazon FBA Bot** es una aplicación Python asíncrona que automatiza el análisis de viabilidad de productos para la venta en Amazon FBA (Fulfillment by Amazon). 

**Objetivo principal:** Procesar cientos de productos en paralelo, validarlos mediante múltiples capas de seguridad y calcular su rentabilidad financiera.

**Beneficios clave:**
- ✅ Procesa productos en paralelo (configurable, defecto: 10 workers)
- ✅ Validación de seguridad multinivel (5 escudos)
- ✅ Integración con SP-API (Amazon), Keepa y Google Sheets
- ✅ Cálculo automático de márgenes, fees, ROI y BSR
- ✅ Trazabilidad completa con logging estructurado
- ✅ Webhooks para alertas en tiempo real
- ✅ Base de datos PostgreSQL con historial

---

## 🔄 Flujo de Funcionamiento

```
┌────────────────────────────────────────────────────────────┐
│ 1. INPUT: CSV con EANs y precios de compra                │
│    (ej: 5901234123457, 12.50)                             │
└────────────────┬─────────────────────────────────────────┘
                 │
┌────────────────▼─────────────────────────────────────────┐
│ 2. INGESTOR (ProductInput)                               │
│    - Valida formato CSV                                  │
│    - Descarta filas malformadas                          │
│    - Emite ProductInput al pipeline                      │
└────────────────┬─────────────────────────────────────────┘
                 │
┌────────────────▼─────────────────────────────────────────┐
│ 3. WORKER POOL (N=10 concurrentes)                       │
│                                                            │
│    ┌──────────────────────────────────┐                  │
│    │ a) EAN Resolver (EAN → ASIN)    │                  │
│    │    - SP-API Catalog Items       │                  │
│    │    - Redis cache (TTL: 7 días)  │                  │
│    └───────────────┬──────────────────┘                  │
│                    │                                      │
│    ┌───────────────▼──────────────────┐                  │
│    │ b) Shield Chain (5 validaciones) │                  │
│    │    1. Brand Blacklist            │                  │
│    │    2. Amazon en Buy Box          │                  │
│    │    3. Seller check (Amazon)      │                  │
│    │    4. Massacre Detector (Keepa)  │                  │
│    │    5. Gating check (SP-API)      │                  │
│    └───────────────┬──────────────────┘                  │
│                    │                                      │
│    ┌───────────────▼──────────────────┐                  │
│    │ c) Financial Calculator          │                  │
│    │    - BuyBox Price lookup         │                  │
│    │    - FBA Fees calculation        │                  │
│    │    - ROI computation (≥20%)      │                  │
│    │    - BSR validation (top 2%)     │                  │
│    └───────────────┬──────────────────┘                  │
└────────────────┬─────────────────────────────────────────┘
                 │
┌────────────────▼─────────────────────────────────────────┐
│ 4. EXPORTER (Resultados)                                 │
│    - Persistir en PostgreSQL                             │
│    - Enviar alerta a Base44 (si webhook disponible)     │
│    - Exportar a Google Sheets                            │
└────────────────┬─────────────────────────────────────────┘
                 │
┌────────────────▼─────────────────────────────────────────┐
│ 5. OUTPUT: Reporte final con estadísticas                │
│    - Productos aprobados                                 │
│    - Productos descartados (con razón)                   │
│    - Errores procesados                                  │
└────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Arquitectura

### Capas del Sistema

```
┌──────────────────────────────────────────────────────────┐
│                    CLI / ENTRY POINT                     │
│                   (src/main.py::main())                  │
└────────────────┬─────────────────────────────────────┬──┘
                 │                                     │
    ┌────────────▼──────┐          ┌──────────────────▼──┐
    │  ORCHESTRATION    │          │  CONFIGURATION     │
    │  (Pipeline Runner)│          │  (Pydantic Config) │
    │  - Worker pool    │          │  - Env validation  │
    │  - Queue mgmt     │          │  - Credentials     │
    └────────────┬──────┘          └────────────────────┘
                 │
    ┌────────────▼──────────────────────────────────────┐
    │     PIPELINE LAYER (asyncio)                      │
    │  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────────┐     │
    │  │Input │→ │Worker│→ │Shield│→ │Financial │     │
    │  └──────┘  │Pool  │  │Chain │  │ Calc    │     │
    │            │(N=10)│  └──────┘  └──────────┘     │
    │            └──────┘     │          │             │
    │                         └──────┬───┘             │
    │                                │                 │
    │            ┌──────────────────▼──────────┐       │
    │            │      EXPORT LAYER          │       │
    │            │ - PostgreSQL persistence   │       │
    │            │ - Google Sheets export     │       │
    │            │ - Base44 webhooks          │       │
    │            └────────────────────────────┘       │
    └────────────────────────────────────────────────────┘
                 │
    ┌────────────▼──────────────────────────────────────┐
    │   EXTERNAL INTEGRATIONS                          │
    │  ┌──────────────────────────────────────┐        │
    │  │ SP-API         │ Keepa      │Redis    │        │
    │  │ (Amazon)       │ (Market)   │ (Cache) │        │
    │  │                │            │         │        │
    │  │ PostgreSQL     │ Google     │Local    │        │
    │  │ (Persistence)  │ Sheets     │ Files   │        │
    │  └──────────────────────────────────────┘        │
    └────────────────────────────────────────────────────┘
```

---

## 📦 Componentes Principales

### 1. **Ingestor** (`src/pipeline/ingestor.py`)
**Clase:** `ProductInput`

Función: Leer CSV y validar entrada de datos.

**Responsabilidades:**
- Lee archivo CSV línea por línea
- Valida columnas requeridas: `ean`, `buy_price`
- Descarta filas con EAN vacío o precio inválido
- Emite `ProductInput` al pipeline

**Atributos:**
```python
ean: str           # EAN del producto (required)
buy_price: float   # Precio de compra (required, > 0)
source_row: int    # Número de fila original para trazabilidad
```

---

### 2. **EAN Resolver** (`src/pipeline/ean_resolver.py`)
**Clase:** `EANResolver`

Función: Convertir EAN/UPC a ASIN (Amazon Standard Identification Number).

**Responsabilidades:**
- Consulta caché Redis (TTL: 7 días)
- Si no hay caché, llama a SP-API Catalog Items
- Si hay múltiples ASINs (pack + unitario), elige mejor BSR
- Retorna `ResolvedProduct` o `None` si no resuelve

**Resultado:** `ResolvedProduct`
```python
ean: str                   # EAN original
asin: str                  # ASIN de Amazon
buy_price: float           # Precio de compra
title: str                 # Título del producto
brand: str                 # Marca
sales_ranks: list[dict]    # BSR por categoría
source_row: int            # Fila original
```

**API Calls:** 1 por EAN no cacheado (SP-API)

---

### 3. **Shield Chain** (`src/pipeline/shields.py`)
**Clase:** `ShieldChain`

Función: Validación multinivel de seguridad (5 escudos).

**Los 5 Escudos (en orden de coste):**

| # | Escudo | Coste | Función |
|---|--------|-------|---------|
| 1 | **Brand Blacklist** | O(1) | Verifica marca contra lista negra local |
| 2 | **Amazon Seller** | O(1) | Verifica si Amazon es el vendedor principal |
| 3 | **Buy Box** | O(1) | Valida que producto esté en Buy Box |
| 4 | **Massacre Detector** | 1 API | Detecta caídas masivas de vendedores FBA en 90 días (Keepa) |
| 5 | **Gating Check** | 1 API | Verifica si marca requiere aprobación (SP-API) |

**Fallos:**
- Si algún escudo falla → producto **descartado** con razón
- Si error inesperado → producto descartado (fail-closed)

**Resultado:** `EnrichedProduct` (si pasan todos) o excepción `PipelineDropError`

---

### 4. **Financial Calculator** (`src/pipeline/financial_calc.py`)
**Clase:** `FinancialCalculator`

Función: Calcular viabilidad financiera y aplicar filtros.

**Fórmula de Rentabilidad:**
```
Beneficio Neto = BuyBox Price - (Buy Price + FBA Fee + Referral Fee + Prep/Shipping)
ROI (%)        = (Beneficio Neto / Buy Price) × 100
```

**Criterios de Aprobación (ambos deben cumplirse):**
- ✅ ROI ≥ `min_roi_pct` (defecto: 20%)
- ✅ BSR en top `bsr_top_pct` de su categoría (defecto: 2%)

**Fees Incluidos:**
- FBA Fee (envío, manipulación, almacén)
- Referral Fee (comisión de Amazon, ~15%)
- Prep/Shipping Fijo (defecto: €0.50)

**Resultado:** `FinancialResult` (si aprobado) o excepción `PipelineDropError`

```python
@dataclass(frozen=True)
class FinancialResult:
    asin: str
    ean: str
    title: str
    brand: str
    buy_price: float
    buybox_price: float
    fees: FeeBreakdown
    net_profit: float
    roi_pct: float
    bsr_rank: int
    bsr_category: str
    bsr_top_pct: float
    source_row: int
```

---

### 5. **Pipeline Worker** (`src/main.py`)
**Clase:** `PipelineWorker`

Función: Orquestar el procesamiento de un producto (coordina los 4 componentes anteriores).

**Responsabilidades:**
1. Consume `ProductInput` de `ingest_queue`
2. Ejecuta cadena: EANResolver → ShieldChain → FinancialCalculator
3. Emite resultado a `results_queue`
4. Captura y registra errores sin detener el pipeline

**Atributos:**
```python
worker_id: int                      # ID del worker (0-9)
_resolver: EANResolver             # Resolvedor EAN
_shields: ShieldChain              # Validador de escudos
_calc: FinancialCalculator         # Calculador financiero
_results_q: asyncio.Queue          # Cola de resultados
```

---

### 6. **Exporter** (`src/pipeline/exporter.py`)
**Clase:** `Exporter`

Función: Persistir resultados y enviar alertas.

**Responsabilidades:**
- Consume `results_queue` asincronamente
- Guarda productos aprobados en PostgreSQL
- Guarda productos rechazados (con razón) en DB
- Envía webhook a Base44 para productos aprobados
- Reintenta escrituras fallidas con backoff exponencial

**Métodos Principales:**
```python
async def send_alert_to_base44(result: FinancialResult) → None
async def export_to_db(result: FinancialResult) → None
async def export_drop(ean: str, reason: str) → None
```

---

### 7. **API Clients**

#### `src/api/sp_api_client.py` - **SPAPIClient**
Wrapper para Amazon Selling Partner API (SP-API).

**Métodos:**
- `resolve_ean(ean)` → Catalog Items API
- `get_item_offers(asin)` → Pricing API
- `get_account_restrictions()` → Restrictions API

#### `src/api/keepa_client.py` - **KeepaClient**
Cliente para Keepa API (datos de mercado).

**Métodos:**
- `check_massacre(asin)` → Detecta caídas de vendedores
- `get_category_data(asin)` → BSR y estadísticas

#### `src/api/google_sheets_client.py` - **GoogleSheetsClient**
Exporta resultados a Google Sheets.

**Métodos:**
- `append_products(results)` → Añade filas a hoja

---

### 8. **Configuration** (`src/core/config.py`)
**Clase:** `Settings` (Pydantic)

**Variables de Entorno Requeridas:**
```ini
# SP-API
SP_API_REFRESH_TOKEN=<lwa_token>
SP_API_CLIENT_ID=<client_id>
SP_API_CLIENT_SECRET=<secret>
SP_API_SELLER_ID=<seller_id>

# AWS (para firmar peticiones SigV4)
AWS_ACCESS_KEY_ID=<key>
AWS_SECRET_ACCESS_KEY=<secret>
AWS_ROLE_ARN=arn:aws:iam::xxx:role/xxx

# Keepa
KEEPA_API_KEY=<api_key>

# Base de datos
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/fba_bot
REDIS_URL=redis://localhost:6379/0

# Pipeline
MIN_ROI_PCT=20.0
BSR_TOP_PCT=2.0
PREP_SHIPPING_FIXED=0.50
PIPELINE_CONCURRENCY=10

# Base44 Webhook (opcional)
BASE44_WEBHOOK_URL=https://...
BOT_WEBHOOK_TOKEN=<token>
```

---

### 9. **Database** (`src/db/`)

#### Models (`src/db/models.py`)
Define estructuras de datos para PostgreSQL.

#### Repository (`src/db/repository.py`)
Patrón Repository para abstracción de BD.

**Métodos:**
- `insert_product(product)` → Guarda producto aprobado
- `insert_drop(ean, reason)` → Guarda rechazo
- `get_by_asin(asin)` → Busca por ASIN

#### Migrations (`src/db/migrations/`)
Alembic para versionado de esquema BD.

---

## 🔌 APIs Integradas

### 1. **SP-API (Amazon Selling Partner API)**
- **Endpoints usados:**
  - `/catalog/2022-04-01/items` → Resolver EAN a ASIN
  - `/pricing/v0/offers` → Obtener precio BuyBox
  - `/account/v1/restrictions` → Verificar gating

### 2. **Keepa API**
- **Endpoints usados:**
  - `/product/` → Histórico de vendedores FBA (massacre detection)
  - `/category/` → Datos de categoría y BSR

### 3. **Google Sheets API**
- **Métodos:**
  - `sheets.spreadsheets.values.append()` → Exportar resultados

### 4. **Base44 Webhook** (Personalizado)
- **Método:** POST
- **Payload:** Datos del producto aprobado con cálculos financieros
- **Auth:** Header `x-bot-token` si está configurado

---

## 💾 Base de Datos

### Esquema PostgreSQL

```sql
-- Tabla de productos aprobados
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    asin VARCHAR(20) UNIQUE NOT NULL,
    ean VARCHAR(30),
    title VARCHAR(500),
    brand VARCHAR(100),
    buy_price DECIMAL(10,2),
    buybox_price DECIMAL(10,2),
    net_profit DECIMAL(10,2),
    roi_pct DECIMAL(5,2),
    bsr_rank INT,
    bsr_category VARCHAR(100),
    status VARCHAR(50),  -- 'approved', 'pending', 'rejected'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla de productos rechazados
CREATE TABLE drops (
    id SERIAL PRIMARY KEY,
    ean VARCHAR(30),
    asin VARCHAR(20),
    shield_name VARCHAR(100),
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla de errores
CREATE TABLE errors (
    id SERIAL PRIMARY KEY,
    product_ean VARCHAR(30),
    error_type VARCHAR(100),
    error_message TEXT,
    traceback TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 🚀 Instalación y Ejecución

### Requisitos
- Python 3.11+
- PostgreSQL 14+
- Redis 6+
- Docker (recomendado)

### Instalación Local

```bash
# 1. Clonar repositorio
git clone <repo_url>
cd amazon-fba-bot

# 2. Crear entorno virtual
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# 3. Instalar dependencias
pip install -e .

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con credenciales reales

# 5. Iniciar base de datos
docker-compose up -d postgres redis

# 6. Aplicar migraciones
alembic upgrade head

# 7. Ejecutar pipeline
python -m src.main --csv data/input_sample.csv
```

### Ejecución con Docker

```bash
docker-compose up --build
```

### CLI

```bash
# Ver ayuda
python -m src.cli --help

# Ejecutar pipeline
python -m src.main --csv data/productos.csv --concurrency 10

# Ejecutar en modo autónomo (con scrapers)
python start_dual_flow.py
```

---

## 🕷️ Scrapers y Monitores

### Componentes de Scraping

#### 1. **Autonomous Crawler** (`src/scrapers/autonomous_crawler.py`)
Rastreador autónomo que descubre productos automáticamente.

#### 2. **Competitive Analyzer** (`src/scrapers/competitive_analyzer.py`)
Analiza competencia y pricing dinámico.

#### 3. **Keyword Scraper** (`src/scrapers/keyword_scraper.py`)
Extrae palabras clave relevantes de Amazon.

#### 4. **Price Monitor** (`src/scrapers/price_monitor.py`)
Monitorea cambios de precio en tiempo real.

#### 5. **Monitor Tiendas** (`src/scrapers/monitor_tiendas.py`)
Monitorea tiendas de proveedores.

#### 6. **Competitor Scraper** (`src/scrapers/competitor_scraper.py`)
Analiza competidores específicos.

#### 7. **Bulk Sourcing** (`src/scrapers/bulk_sourcing.py`)
Procesamiento masivo de proveedores.

#### 8. **Orchestrator** (`src/scrapers/orchestrator.py`)
Coordina ejecución de todos los scrapers.

#### 9. **Scheduler** (`src/scrapers/scheduler.py`)
Planifica ejecución recurrente de scrapers.

---

## 🔔 Webhooks y Alertas

### Base44 Webhook

**URL Configurada:**
```
POST https://<base44-endpoint>/api/products
```

**Autenticación:**
```
Header: x-bot-token: <BOT_WEBHOOK_TOKEN>
```

**Payload Enviado:**
```json
{
  "asin": "B001234567",
  "ean": "5901234123457",
  "product_name": "Producto XYZ",
  "score": 85,
  "amazon_price": 29.99,
  "max_buy_price": 12.50,
  "store_buy_price": 12.50,
  "net_margin": 5.25,
  "roi_percent": 42.0,
  "bsr_percent": 0.5,
  "active_sellers": 5,
  "est_monthly_sales": 300,
  "category": "Electronics",
  "shield_amazon": true,
  "shield_brand": true,
  "shield_massacre": true,
  "shield_account": true
}
```

**Reintentos:** Exponential backoff (3 intentos máximo)

---

## 📊 Flujo Detallado de Excepciones

```
ProductInput
    │
    ├─ EANResolver.resolve()
    │   ├─ ✅ Retorna ResolvedProduct → Continúa
    │   └─ ❌ Retorna None → Drop (ean_resolver)
    │
    ├─ ShieldChain.run()
    │   ├─ ✅ Todos pasan → Continúa
    │   ├─ ❌ BrandBlacklistShield → Drop (shield_1_brand_blacklist)
    │   ├─ ❌ AmazonSellerShield → Drop (shield_2_seller)
    │   ├─ ❌ BuyBoxShield → Drop (shield_3_buybox)
    │   ├─ ❌ MassacreDetector → Drop (shield_4_massacre)
    │   └─ ❌ GatingShield → Drop (shield_5_gating)
    │
    ├─ FinancialCalculator.calculate()
    │   ├─ ✅ ROI ≥ 20% Y BSR top 2% → Approve
    │   ├─ ❌ ROI < 20% → Drop (low_roi)
    │   └─ ❌ BSR > 2% → Drop (low_bsr)
    │
    └─ Exporter.export()
        ├─ ✅ Guardado en BD
        ├─ ✅ Webhook a Base44
        └─ ✅ Google Sheets actualizado
```

---

## 📈 Estadísticas Finales

Al completar el pipeline, se emite reporte:

```
╔════════════════════════════════════════════════╗
║         PIPELINE EXECUTION REPORT              ║
╠════════════════════════════════════════════════╣
║ Productos procesados:     500                  ║
║ Productos aprobados:       45                  ║
║ Productos rechazados:     420                  ║
║   - Brand blacklist:       80                  ║
║   - Low ROI:              150                  ║
║   - Low BSR:              100                  ║
║   - Massacre detected:     50                  ║
║   - Gating required:       40                  ║
║ Errores:                   35                  ║
║────────────────────────────────────────────────║
║ Tiempo total:             2m 34s               ║
║ Promedio/producto:        308ms                ║
║ Workers activos:           10                  ║
╚════════════════════════════════════════════════╝
```

---

## 🔍 Logging

Sistema de logging estructurado con `structlog`.

**Niveles:**
- `DEBUG` - Detalles de caché, llamadas a API
- `INFO` - Procesamiento de productos, resultados
- `WARNING` - Productos saltados, fallos no críticos
- `ERROR` - Fallos en pipeline, excepciones
- `CRITICAL` - Fallos de infraestructura (BD, Redis)

**Ejemplo:**
```json
{
  "timestamp": "2026-05-25T22:30:15.123Z",
  "level": "INFO",
  "logger": "src.pipeline.ean_resolver",
  "event": "ean_resolver.start",
  "ean": "5901234123457",
  "row": 2,
  "worker": 3
}
```

---

## 🛠️ Desarrollo y Testing

### Ejecutar Tests
```bash
pytest tests/ -v
pytest tests/test_pipeline_integration.py -k test_full_flow
```

### Lint y Formateo
```bash
ruff check src/ --fix
black src/ tests/
mypy src/ --strict
```

### Cobertura
```bash
pytest --cov=src tests/
```

---

## 📝 Estructura de Directorios

```
amazon-fba-bot/
├── src/
│   ├── main.py                  # Orquestador principal
│   ├── cli.py                   # Interfaz CLI
│   ├── api/
│   │   ├── sp_api_client.py     # Amazon SP-API
│   │   ├── keepa_client.py      # Keepa API
│   │   └── google_sheets_client.py
│   ├── core/
│   │   ├── config.py            # Settings Pydantic
│   │   ├── exceptions.py        # Excepciones custom
│   │   ├── logger.py            # Setup logging
│   │   └── rate_limiter.py      # Rate limiting
│   ├── pipeline/
│   │   ├── ingestor.py          # Lectura CSV
│   │   ├── ean_resolver.py      # EAN→ASIN
│   │   ├── shields.py           # 5 escudos
│   │   ├── financial_calc.py    # Cálculos financieros
│   │   └── exporter.py          # Exportación resultados
│   ├── db/
│   │   ├── models.py            # Modelos BD
│   │   ├── repository.py        # Acceso a datos
│   │   └── migrations/          # Alembic migrations
│   └── scrapers/
│       ├── autonomous_crawler.py
│       ├── price_monitor.py
│       └── ... (otros scrapers)
├── tests/
│   ├── test_pipeline_integration.py
│   ├── test_ean_resolver.py
│   └── ...
├── data/
│   ├── input_sample.csv
│   ├── brand_blacklist.json
│   └── category_sizes.json
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── alembic.ini
```

---

## 🚀 Próximas Mejoras

- [ ] Integración con más proveedores
- [ ] Machine Learning para predicción de demanda
- [ ] Dashboard web en tiempo real
- [ ] Soporte para múltiples marketplaces (UK, DE, FR)
- [ ] Optimización de caché distribuido
- [ ] Alertas móviles vía Telegram

---

**Última actualización:** Mayo 2026  
**Versión:** 2.0.0
