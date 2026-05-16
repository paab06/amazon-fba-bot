# Amazon FBA Bot - Documentación Técnica

## 📋 Tabla de Contenidos
1. [Resumen Ejecutivo](#resumen-ejecutivo)
2. [Arquitectura](#arquitectura)
3. [Componentes Principales](#componentes-principales)
4. [Flujo de Datos](#flujo-de-datos)
5. [Instalación y Configuración](#instalación-y-configuración)
6. [Ejecución](#ejecución)
7. [APIs Integradas](#apis-integradas)
8. [Base de Datos](#base-de-datos)
9. [Extensiones y Mejoras Futuras](#extensiones-y-mejoras-futuras)

---

## 🎯 Resumen Ejecutivo

**Amazon FBA Bot** es una aplicación Python asíncrona que automatiza el análisis de viabilidad de productos para la venta en Amazon FBA (Fulfillment by Amazon).

### Objetivo Principal
Automatizar la evaluación de productos potenciales (identificados por EAN) mediante:
- Resolución EAN → ASIN
- Validación de seguridad (5 escudos de protección)
- Cálculo automático de rentabilidad
- Exportación de resultados a Google Sheets y PostgreSQL

### Beneficios
✅ Procesa cientos de productos en paralelo  
✅ Integración con SP-API de Amazon, Keepa y Google Sheets  
✅ Validación de seguridad multinivel contra rechazos y suspensiones  
✅ Cálculo automático de márgenes, fees, ROI y BSR  
✅ Trazabilidad completa de descartados y errores  

---

## 🏗️ Arquitectura

### Diagrama de Flujo

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. INPUT: CSV con EANs y precios de compra                        │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  2. INGESTOR: Lee CSV y valida ProductInput (EAN, buy_price)      │
│     - Salta filas malformadas                                       │
│     - Emite ProductInput a ingest_queue                             │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
       ┌──────────────┴──────────────┐
       │                             │
       ▼ (asyncio.Queue)             │
┌────────────────────────────────┐   │
│ POOL DE N WORKERS              │   │ (configurable, default=10)
│ (Concurrencia configurable)    │   │
└────┬─────────────────────────┬─┘   │
     │                         │      │
     ▼                         ▼      │
┌──────────────────────┐             │
│  3. EAN RESOLVER     │ ◄───────────┘
│  (EAN → ASIN)        │
│  - Redis Cache (7d)  │
│  - SP-API fallback   │
└────┬─────────────────┘
     │ ResolvedProduct
     ▼
┌──────────────────────┐
│  4. SHIELD CHAIN     │
│  (5 escudos)         │
│  1. Blacklist local  │
│  2. Brand check      │
│  3. Amazon en BB     │
│  4. Keepa masacres   │
│  5. Gating SP-API    │
└────┬─────────────────┘
     │ EnrichedProduct | ShieldDrop
     ▼
┌──────────────────────┐
│  5. FINANCIAL CALC   │
│  - ROI calculation   │
│  - BSR validation    │
│  - Fee breakdown     │
└────┬─────────────────┘
     │ FinancialResult | FinancialDropReason
     ▼
┌──────────────────────┐
│  6. EXPORTER         │
│  - Google Sheets     │
│  - PostgreSQL DB     │
│  - Async batching    │
└──────────────────────┘
```

### Stack Tecnológico

| Layer | Tecnología | Propósito |
|-------|-----------|----------|
| **Runtime** | Python 3.11+ | Lenguaje principal |
| **Concurrencia** | asyncio | Procesamiento paralelo |
| **APIs** | aiohttp | Cliente HTTP async |
| **Caché** | Redis | Caché de EAN resolver |
| **DB** | PostgreSQL + asyncpg | Persistencia |
| **Google** | gspread-asyncio | Exportación a Sheets |
| **Logging** | structlog | Logs estructurados (JSON) |
| **Rate Limit** | Token bucket | Control de throttling |
| **Retry** | tenacity | Reintentos con backoff |
| **Config** | pydantic-settings | Gestión de .env |

---

## 🔧 Componentes Principales

### 1. **Ingestor** (`src/pipeline/ingestor.py`)
Lee un CSV y valida cada fila.

**Entrada:** CSV con columnas `ean`, `buy_price`  
**Salida:** AsyncIterator[ProductInput]  
**Validaciones:**
- EAN no vacío
- Precio > 0
- Formato numérico

**Ejemplo CSV:**
```csv
ean,buy_price
5901234123457,12.50
4006381333931,8.00
```

---

### 2. **EAN Resolver** (`src/pipeline/ean_resolver.py`)
Resuelve EAN → ASIN usando SP-API Catalog Items API v2022-04-01.

**Estrategia de caché:**
- **Key:** `ean_resolver:{ean}`
- **Value:** JSON con {asin, title, brand, sales_ranks}
- **TTL:** 7 días
- **Fallback:** Si no hay caché, consulta SP-API

**Datos retornados:**
```python
@dataclass
class ResolvedProduct:
    ean: str
    asin: str
    title: str
    brand: str
    buy_price: float
    sales_ranks: list[dict]  # [{"rank": 42, "category": "Electrónica"}]
    source_row: int
```

---

### 3. **Shield Chain** (`src/pipeline/shields.py`)
5 capas de validación de seguridad ejecutadas en serie (orden de coste ascendente).

| # | Shield | Coste | Lógica |
|---|--------|-------|--------|
| 1 | **Blacklist Local** | 0 API calls | Compara marca contra `data/brand_blacklist.json` |
| 2 | **Amazon en BB** | 0 API calls | Verifica que Amazon NO sea el vendedor principal |
| 3 | **Brand == Seller** | 0 API calls | Verifica que el vendedor sea la marca oficial |
| 4 | **Keepa Masacres** | 1 Keepa call | Detecta caídas >= 80% de vendedores FBA en 90 días |
| 5 | **Gating SP-API** | 1 SP-API call | Comprueba restricciones por ASIN (brand gating, aprobaciones) |

**Comportamiento:** Fail-closed (ante cualquier error inesperado, descarta el producto)

---

### 4. **Financial Calculator** (`src/pipeline/financial_calc.py`)
Calcula rentabilidad y valida criterios de exportación.

**Fórmula de Beneficio Neto:**
```
Beneficio Neto = BuyBox Price 
               - (Buy Price + FBA Fee + Referral Fee + Prep/Shipping Fijo)

ROI% = (Beneficio Neto / Buy Price) × 100
```

**Criterios de Aprobación (ambos deben cumplirse):**
1. **ROI >= settings.min_roi_pct** (default: 20%)
2. **BSR en top N% de su categoría** (default: top 2%)

**BSR Validation:**
- Lee totales por categoría de `data/category_sizes.json`
- Calcula: `top_pct = (bsr_rank / total_in_category) × 100`
- Descarta si no está en top N%

**Output:**
```python
@dataclass
class FinancialResult:
    asin: str
    ean: str
    title: str
    brand: str
    buy_price: float
    buybox_price: float
    fees: FeeBreakdown  # {fba_fee, referral_fee, prep_shipping}
    net_profit: float
    roi_pct: float
    bsr_rank: int
    bsr_category: str
    bsr_category_size: int
    bsr_top_pct: float
    source_row: int
```

---

### 5. **Exporter** (`src/pipeline/exporter.py`)
Exporta resultados a Google Sheets y PostgreSQL de forma asíncrona en batches.

**Google Sheets:**
- Batch size: 50 rows
- Reintentos: hasta 3 veces con backoff exponencial
- Columnas: ASIN, EAN, Title, Brand, Precios, Fees, Rentabilidad, BSR, Vendedor...

**PostgreSQL:**
- Tabla `results`: FinancialResult aprobados
- Tabla `drops`: Todos los productos descartados (shield + razón)
- Tabla `errors`: Errores inesperados durante el procesamiento

---

### 6. **Pipeline Orchestrator** (`src/main.py`)

**Worker Pool Pattern:**
- N workers simultáneos (configurable: default=10)
- Cada worker procesa un ProductInput completo
- Cola asíncrona compartida (ingest_queue, results_queue)

**Shutdown Limpio:**
- Maneja SIGINT/SIGTERM
- Espera a que workers terminen
- Flush de escrituras pendientes
- Estadísticas finales

---

## 📊 Flujo de Datos Detallado

### Entrada
```python
ProductInput(
    ean="5901234123457",
    buy_price=12.50,
    source_row=2
)
```

### Transformaciones

1. **→ EAN Resolver:**
   ```python
   ResolvedProduct(
       ean="5901234123457",
       asin="B07XYZ123",
       title="Producto Premium",
       brand="Brand XYZ",
       sales_ranks=[{"rank": 150, "category": "Electronics"}]
   )
   ```

2. **→ Shield Chain:**
   ```python
   EnrichedProduct(
       # ResolvedProduct + datos de validación
       buybox_price=24.99,
       buybox_seller_name="Amazon",
       buybox_is_fba=True,
       ...
   )
   ```

3. **→ Financial Calculator:**
   ```python
   FinancialResult(
       asin="B07XYZ123",
       buy_price=12.50,
       buybox_price=24.99,
       roi_pct=45.2,
       net_profit=11.49,
       ...
   )
   ```

4. **→ Exporter:**
   - Fila en Google Sheets
   - Registro en PostgreSQL

### Descartados
```python
{
    "type": "shield_drop",
    "asin": "B07XYZ123",
    "ean": "5901234123457",
    "shield": "keepa_massacre",
    "reason": "Caída del 85% de vendedores FBA en 90 días"
}
```

---

## 🚀 Instalación y Configuración

### Requisitos Previos
- Python 3.11+
- PostgreSQL 14+
- Redis 7+
- Docker & Docker Compose (opcional)

### 1. Clonar Repositorio
```bash
git clone <repo-url>
cd amazon-fba-bot
```

### 2. Crear Entorno Virtual
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o
venv\Scripts\activate     # Windows
```

### 3. Instalar Dependencias
```bash
pip install -e .  # Instala el paquete en modo editable
```

### 4. Configurar Variables de Entorno
Crear archivo `.env` en la raíz:

```bash
# ── SP-API (Login with Amazon)
SP_API_REFRESH_TOKEN="your_refresh_token_here"
SP_API_CLIENT_ID="your_client_id_here"
SP_API_CLIENT_SECRET="your_client_secret_here"
SP_API_SELLER_ID="your_seller_id_here"
SP_API_MARKETPLACE_ID="A1RKKUPIHCS9HS"  # Spain
SP_API_REGION="eu-west-1"
SP_API_ENDPOINT="https://sellingpartnerapi-eu.amazon.com"

# ── AWS Credentials (para SigV4)
AWS_ACCESS_KEY_ID="your_access_key"
AWS_SECRET_ACCESS_KEY="your_secret_key"
AWS_ROLE_ARN="arn:aws:iam::123456789:role/SPAPIRole"

# ── Keepa API
KEEPA_API_KEY="your_keepa_api_key"

# ── Database
DATABASE_URL="postgresql+asyncpg://fba:secret@localhost:5432/fba_bot"

# ── Redis
REDIS_URL="redis://localhost:6379/0"

# ── Google Sheets
GOOGLE_SHEETS_ID="your_spreadsheet_id"
GOOGLE_CREDENTIALS_JSON_PATH="credentials/google_service_account.json"

# ── Pipeline Settings
MIN_ROI_PCT=20.0
BSR_TOP_PCT=2.0
PREP_SHIPPING_FIXED=0.50
PIPELINE_CONCURRENCY=10
```

### 5. Iniciar Servicios Locales (Docker)
```bash
docker-compose up -d
# Esperar a que PostgreSQL esté listo (~10s)
```

### 6. Inicializar Base de Datos
```bash
# Ejecutar migraciones Alembic (cuando esté implementado)
alembic upgrade head
```

---

## 🎬 Ejecución

### Opción 1: Línea de Comandos
```bash
python -m src.main path/to/input.csv
```

### Opción 2: Usando Entry Point Instalado
```bash
fba-bot path/to/input.csv
```

### Ejemplo de Ejecución Completa
```bash
# Terminal 1: Iniciar servicios
docker-compose up

# Terminal 2: Ejecutar bot
fba-bot data/input_sample.csv

# Output esperado:
# [INFO] pipeline.start run_id=20240515T143052_abc123 csv=data/input_sample.csv
# [PROGRESS] Procesando 1500 productos...
# [PROGRESS] ✓ 1200 aprobados | ✗ 300 descartados | ⚠️ 5 errores
# [INFO] Exported 1200 rows to Google Sheets
# [INFO] Exported 1200 approved + 300 drops to PostgreSQL
# [INFO] pipeline.complete run_id=20240515T143052_abc123 duration_seconds=1245.3
```

---

## 🔌 APIs Integradas

### 1. **SP-API (Selling Partner API)**
**Responsable:** `src/api/sp_api_client.py`

#### Endpoints Utilizados:
- `searchCatalogItems` - Buscar ASIN por EAN (Catalog Items API v2022-04-01)
- `getItemOffers` - Obtener precios y vendedores en BuyBox
- `getCompetitivePricing` - Precios competitivos
- `getListingsRestrictions` - Verificar brand gating
- `getMyFeesEstimate` - Calcular Amazon FBA fees

#### Autenticación:
- **LWA (Login with Amazon):** Refresh Token → Access Token
- **SigV4:** Firma AWS en cada request
- **Rate Limiting:** Token bucket por endpoint (thresholds de SP-API)

#### Reintentos:
- Tenacity: exponential backoff (hasta 3 intentos)
- Manejo de 429 (Rate Limit), 5xx (Server Error)

---

### 2. **Keepa API**
**Responsable:** `src/api/keepa_client.py`

#### Endpoints Utilizados:
- Category analysis - Datos históricos de precios
- Marketplace data - BSR y tendencias

#### Funcionalidades:
- Detección de "massacre" de precios (caída >= 80% en 90 días)
- Análisis de volatilidad

---

### 3. **Google Sheets API**
**Responsable:** `src/api/google_sheets_client.py`

#### Operaciones:
- Exportar FinancialResult en batches de 50
- Actualizar hoja con timestamps

#### Requisitos:
- Service Account JSON credentials
- Spreadsheet ID compartido

---

## 🗄️ Base de Datos

### PostgreSQL Schema (Diseño)

```sql
-- Tabla de resultados aprobados
CREATE TABLE results (
    id SERIAL PRIMARY KEY,
    asin VARCHAR(10) NOT NULL,
    ean VARCHAR(20) NOT NULL,
    title TEXT NOT NULL,
    brand VARCHAR(255),
    buy_price DECIMAL(10, 2),
    buybox_price DECIMAL(10, 2),
    fba_fee DECIMAL(10, 2),
    referral_fee DECIMAL(10, 2),
    prep_shipping DECIMAL(10, 2),
    net_profit DECIMAL(10, 2),
    roi_pct DECIMAL(5, 2),
    bsr_rank INT,
    bsr_category VARCHAR(255),
    bsr_category_size INT,
    bsr_top_pct DECIMAL(5, 2),
    buybox_seller_name VARCHAR(255),
    buybox_is_fba BOOLEAN,
    exported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla de descartados
CREATE TABLE drops (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(50),
    asin VARCHAR(10),
    ean VARCHAR(20),
    shield VARCHAR(50) NOT NULL,  -- ean_resolver, blacklist, etc
    reason TEXT,
    source_row INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla de errores
CREATE TABLE errors (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(50),
    ean VARCHAR(20),
    asin VARCHAR(10),
    error_message TEXT,
    stack_trace TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices para queries frecuentes
CREATE INDEX idx_results_asin ON results(asin);
CREATE INDEX idx_results_created_at ON results(created_at DESC);
CREATE INDEX idx_drops_shield ON drops(shield);
CREATE INDEX idx_drops_ean ON drops(ean);
```

---

## 📁 Estructura de Archivos de Datos

### `data/`
```
data/
├── brand_blacklist.json        # Lista de marcas peligrosas
├── category_sizes.json         # Totales por categoría (Amazon ES)
└── input_sample.csv            # Ejemplo de entrada
```

#### `brand_blacklist.json`
```json
{
  "brands": [
    "Nike",
    "Apple",
    "Gucci",
    "...más marcas con restricciones..."
  ]
}
```

#### `category_sizes.json`
```json
{
  "Electrónica": 250000,
  "Hogar y Cocina": 450000,
  "Ropa y Accesorios": 1200000,
  "...": "..."
}
```

---

## 🔄 Concurrencia y Rate Limiting

### Worker Pool
- **Workers simultáneos:** Configurable via `PIPELINE_CONCURRENCY` (default: 10)
- **Pattern:** asyncio.Queue + N coroutines
- **Beneficio:** Procesar 100 productos en ~1-2 min (vs. 1 producto/request de manera secuencial)

### Rate Limiting Multinivel
1. **Token Bucket (per endpoint SP-API):** Respeta thresholds de Amazon
2. **Retry Backoff:** Exponential backoff en rate limits
3. **Redis Caché:** Evita requests duplicados al EAN Resolver

---

## 🧪 Testing

### Archivos de Test
```
tests/
├── conftest.py                    # Fixtures compartidas
├── test_ean_resolver.py           # EAN Resolver unit tests
├── test_financial_calc.py         # Financial Calculator tests
├── test_pipeline_integration.py   # Pipeline end-to-end
├── test_pipeline_report.py        # Report generation
├── test_shields.py                # Shield Chain tests
└── test_sp_api_client.py          # SP-API client mocking
```

### Ejecutar Tests
```bash
# Todos los tests
pytest

# Con coverage
pytest --cov=src

# Un archivo específico
pytest tests/test_shields.py -v
```

### Configuración de pytest
- **asyncio_mode:** auto (con pytest-asyncio)
- **testpaths:** tests/

---

## 📈 Monitoreo y Logging

### Logs Estructurados (structlog)
```json
{
  "timestamp": "2024-05-15T14:30:52.123Z",
  "level": "INFO",
  "event": "worker.process_complete",
  "worker": 3,
  "asin": "B07XYZ123",
  "ean": "5901234123457",
  "roi_pct": 45.2,
  "duration_ms": 2341
}
```

### Niveles de Log
- **DEBUG:** Operaciones de caché, reintentos de rate limiter
- **INFO:** Inicio/fin de pipeline, productos aprobados
- **WARNING:** EAN no resuelto, producto descartado
- **ERROR:** Fallos inesperados, stack traces

### Cambiar Salida de Logs
**Desarrollo (actual):** ConsoleRenderer (legible)  
**Producción:** JSONRenderer (máquina-readable, ELK/CloudWatch)

Editar `src/core/logger.py` línea ~16:
```python
# structlog.dev.ConsoleRenderer(),       # Comentar
structlog.processors.JSONRenderer(),       # Descomentar para producción
```

---

## 🔐 Seguridad

### Credenciales
- ✅ Variables de entorno via `.env` (Pydantic Settings)
- ✅ `SecretStr` para tokens, keys en config.py
- ✅ Nunca logear valores secretos (sanitizados automáticamente)
- ⚠️ Guardar `.env` fuera del repositorio

### Validaciones
- ✅ Validación de EAN en Ingestor
- ✅ Validación de precios (> 0)
- ✅ Verificación de brand gating vía SP-API
- ✅ Rate limiting para evitar DDoS accidental

---

## 🚧 Extensiones y Mejoras Futuras

### Corto Plazo (Sprint 1-2)
- [ ] Implementar models.py con SQLAlchemy
- [ ] Migraciones Alembic completas
- [ ] Dashboard simple (Streamlit o FastAPI)
- [ ] Exportar a CSV/Excel (además de Sheets)

### Mediano Plazo (Sprint 3-5)
- [ ] API REST FastAPI para queries (top ROI, por categoría, etc.)
- [ ] Scheduler (daily runs automáticos)
- [ ] Telegram/Email notifications (products to review)
- [ ] Caché de fees históricos para análisis de tendencias

### Largo Plazo (Q3+)
- [ ] Machine Learning: predictor de demanda (Keepa data)
- [ ] Integración Stripe: cálculos de cash flow y financiación
- [ ] Multi-marketplace (ES, UK, DE, FR, US)
- [ ] Análisis competitivo automático (reprecio dinámico)

---

## 📞 Contacto y Soporte

**Autor:** Tu nombre  
**Última actualización:** 2024-05-15  
**Versión:** 0.1.0  

Para preguntas, issues o sugerencias, contactar al equipo de desarrollo.

---

## 📄 Licencia

[Especificar licencia si aplica]
