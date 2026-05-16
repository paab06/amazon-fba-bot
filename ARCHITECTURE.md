# ARCHITECTURE.md - Arquitectura Detallada

## 📐 Visión General de Capas

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI / ENTRY POINT                      │
│                    (src/main.py::main())                    │
└────────────────────────┬──────────────────────────────────┬─┘
                         │                                  │
        ┌────────────────▼──────┐          ┌────────────────▼──────┐
        │   ORCHESTRATION       │          │   CONFIGURATION       │
        │  (Pipeline Runner)    │          │  (Pydantic Settings)  │
        │  - Worker pool        │          │  - Env validation     │
        │  - Queue management   │          │  - Credentials        │
        └────────────┬──────────┘          └───────────────────────┘
                     │
        ┌────────────▼──────────────────────────────────────────┐
        │           PIPELINE LAYER (asyncio)                   │
        │  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
        │  │ Ingestor │→ │  Worker  │→ │ Exporter │            │
        │  └──────────┘  │  Pool    │  └──────────┘            │
        │                │ (N=10)   │                           │
        │                └──────────┘                           │
        └────────────┬──────────────────────────────────────────┘
                     │
        ┌────────────▼──────────────────────────────────────────┐
        │       PROCESSING CHAIN (Within Worker)               │
        │  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
        │  │   EAN    │→ │ Shields  │→ │Financial │            │
        │  │ Resolver │  │  Chain   │  │  Calc    │            │
        │  └──────────┘  └──────────┘  └──────────┘            │
        └────────────┬──────────────────────────────────────────┘
                     │
        ┌────────────▼──────────────────────────────────────────┐
        │        EXTERNAL INTEGRATIONS                          │
        │  ┌─────────────────┬──────────┬────────────────────┐  │
        │  │                 │          │                    │  │
        │  ▼                 ▼          ▼                    ▼  │
        │ ┌──────────┐    ┌─────────┐ ┌────────┐  ┌──────────┐│
        │ │ SP-API   │    │ Keepa   │ │ Redis  │  │PostgreSQL││
        │ │ (Amazon) │    │ (Data)  │ │(Cache) │  │  (Store) ││
        │ └──────────┘    └─────────┘ └────────┘  └──────────┘│
        │                                                       │
        │ ┌────────────────────────────┐  ┌─────────────────┐ │
        │ │   Google Sheets            │  │  Local Files    │ │
        │ │   (Exportar resultados)    │  │  (Brand list,   │ │
        │ └────────────────────────────┘  │   category data)│ │
        │                                  └─────────────────┘ │
        └────────────────────────────────────────────────────────┘
```

---

## 🔄 Flujo Detallado por Componente

### 1. INGESTOR (Entrada)

**Ruta:** `src/pipeline/ingestor.py`

```
CSV (input.csv)
     │
     ├─ Validación de columnas (ean, buy_price requeridas)
     │
     ├─ Lectura línea por línea:
     │   ├─ Si EAN vacío → SKIP + LOG WARNING
     │   ├─ Si Precio no numérico → SKIP + LOG WARNING
     │   ├─ Si Precio <= 0 → SKIP + LOG WARNING
     │   └─ Else → EMIT ProductInput(ean, buy_price, source_row)
     │
     └─ asyncio.Queue (ingest_queue)
```

**Validaciones:**
```python
ProductInput {
    ean: str         # No vacío, max 20 caracteres
    buy_price: float # > 0
    source_row: int  # Fila original para trazabilidad
}
```

---

### 2. WORKER POOL (Orquestación)

**Ruta:** `src/main.py::_worker_loop()`

```
ingest_queue (ProductInput)
     │
     ├─ Worker 1 ─┐
     ├─ Worker 2 ─┤─→ (Procesa en paralelo)
     ├─ Worker 3 ─┤
     └─ Worker N ─┘
     │
     └─ results_queue (FinancialResult | ShieldDrop | WorkerError)
```

**Worker Loop:**
1. Consume ProductInput de ingest_queue (non-blocking)
2. Si cola vacía → sleep(0.1s) y reintentar
3. Procesa producto completo
4. Pone resultado en results_queue
5. Marca tarea como completada (task_done)

**Shutdown Limpio:**
- SIGINT/SIGTERM → set shutdown_event
- Workers chequean flag regularmente
- Esperan a que se vacíe ingest_queue
- Flush final de resultados_queue
- Print de estadísticas

---

### 3. EAN RESOLVER (Identidad del Producto)

**Ruta:** `src/pipeline/ean_resolver.py`

```
ProductInput(ean="5901234123457")
     │
     ├─ [1] Consultar Redis:
     │       Key: "ean_resolver:5901234123457"
     │       Si existe (cache_hit) → ir a paso 5
     │       Si no existe → ir a paso 2
     │
     ├─ [2] Consultar SP-API (searchCatalogItems):
     │       Endpoint: /catalog/2022-04-01/items
     │       Parámetros: {ean, identifiers: ["ean"]}
     │       Retry: 3 intentos con exponential backoff
     │
     ├─ [3] Parsear respuesta:
     │       Si 0 resultados → None (producto descartado)
     │       Si N resultados → Seleccionar por mejor BSR
     │
     ├─ [4] Almacenar en Redis:
     │       Key: "ean_resolver:5901234123457"
     │       Value: {asin, title, brand, sales_ranks}
     │       TTL: 604800 segundos (7 días)
     │
     └─ [5] Retornar ResolvedProduct
              ├─ asin: "B07XYZ123"
              ├─ title: "Producto Premium XYZ"
              ├─ brand: "Brand Name"
              ├─ sales_ranks: [{"rank": 150, "category": "Electronics"}]
              └─ buy_price: 12.50 (del ProductInput original)
```

**Rate Limiting:**
- searchCatalogItems: 5 burst, 1 req / 1 seg (token bucket)

---

### 4. SHIELD CHAIN (Validación de Seguridad)

**Ruta:** `src/pipeline/shields.py`

```
ResolvedProduct(asin="B07XYZ123", brand="Brand Name")
     │
     ├─ ESCUDO 1: BrandBlacklistShield
     │      ├─ Cargar: data/brand_blacklist.json
     │      ├─ Comparar: product.brand ∈ blacklist (case-insensitive)
     │      ├─ Si match → PipelineDropError("blacklist")
     │      └─ Else → Continuar
     │
     ├─ ESCUDO 2: AmazonBuyBoxShield
     │      ├─ Obtener: producto.buybox_seller_name (de ResolvedProduct)
     │      ├─ Si seller ∈ {Amazon, Amazon EU, Warehouse Deals} → DROP
     │      ├─ Razón: "Amazon es el vendedor en Buy Box"
     │      └─ Else → Continuar
     │
     ├─ ESCUDO 3: BrandBuyBoxShield
     │      ├─ Validar: brand == buybox_seller_name
     │      ├─ Si no match → PipelineDropError("brand_mismatch")
     │      ├─ Razón: "Vendedor no es la marca oficial"
     │      └─ Else → Continuar
     │
     ├─ ESCUDO 4: KeepaCliffDetectorShield
     │      ├─ Llamar: KeepaClient.analyze_massacre(asin)
     │      ├─ Buscar: Caída >= 80% vendedores FBA en 90 días
     │      ├─ Si detectado → PipelineDropError("keepa_massacre")
     │      ├─ Razón: "Precio colapsado recientemente"
     │      └─ Else → Continuar
     │
     ├─ ESCUDO 5: GatingShield
     │      ├─ Llamar: SPAPIClient.getListingsRestrictions(asin)
     │      ├─ Buscar: Restricciones de brand gating o aprobaciones
     │      ├─ Si gated → PipelineDropError("gating")
     │      ├─ Razón: "Requiere aprobación especial de marca"
     │      └─ Else → Continuar → EnrichedProduct (PASS)
     │
     └─ Resultado:
        ├─ PASS → EnrichedProduct (datos completos de validación)
        └─ FAIL → ShieldDrop (asin, ean, shield, reason)
```

**Flujo de Errores:**
- Cada escudo captura excepciones inesperadas
- Ante error: PipelineDropError("shield_error", reason=str(exc))
- Fail-closed: Si hay duda, descarta

---

### 5. FINANCIAL CALCULATOR (Análisis de Rentabilidad)

**Ruta:** `src/pipeline/financial_calc.py`

```
EnrichedProduct(asin, buybox_price, bsr_rank, bsr_category)
     │
     ├─ [1] Obtener FBA Fees (SP-API):
     │       Endpoint: /products/fees/v0/fees
     │       Parámetro: asin
     │       Retorna: {fba_fee, referral_fee, ...}
     │
     ├─ [2] Calcular Fees Totales:
     │       fba_fee = ResponseAPI.fba_fee
     │       referral_fee = ResponseAPI.referral_fee
     │       prep_shipping = settings.prep_shipping_fixed (0.50€)
     │       total_fees = sum(los 3)
     │
     ├─ [3] Calcular Beneficio Neto:
     │       net_profit = buybox_price 
     │                    - (buy_price + total_fees)
     │
     ├─ [4] Calcular ROI:
     │       roi_pct = (net_profit / buy_price) * 100
     │       Si < 0 → DESCARTADO (ROI negativo)
     │
     ├─ [5] Validar ROI:
     │       Si roi_pct < settings.min_roi_pct (20%)
     │           → FinancialDropReason("roi_too_low", roi_pct)
     │       Else → Continuar
     │
     ├─ [6] Validar BSR:
     │       Cargar: data/category_sizes.json
     │       category_size = sizes[bsr_category] ← 500K (fallback)
     │       top_pct = (bsr_rank / category_size) * 100
     │       Si top_pct > settings.bsr_top_pct (2%)
     │           → FinancialDropReason("bsr_too_low", bsr_rank, top_pct)
     │       Else → Continuar
     │
     └─ [7] Retornar FinancialResult (APROBADO)
              ├─ asin, ean, title, brand, buy_price
              ├─ buybox_price, total_fees (desglose)
              ├─ net_profit, roi_pct
              ├─ bsr_rank, bsr_category, bsr_top_pct
              └─ buybox_seller_name, buybox_is_fba
```

**Criterios de Aprobación:**
```
✓ APROBADO SI:
  ├─ ROI% >= 20% (configurable)
  └─ BSR en top 2% de categoría (configurable)

✗ DESCARTADO SI:
  ├─ ROI% < 20%
  ├─ BSR fuera de top 2%
  ├─ Fees inaccesibles (SP-API error)
  └─ Categoría desconocida en category_sizes.json
```

---

### 6. EXPORTER (Persistencia)

**Ruta:** `src/pipeline/exporter.py`

```
results_queue (FinancialResult | ShieldDrop | WorkerError)
     │
     ├─ [CONSUMER ASYNC] Lee de cola en paralelo
     │
     ├─ [BATCHING] Acumula 50 registros
     │
     ├─ CUANDO llega a 50 o timeout:
     │     │
     │     ├─ [1] Google Sheets (SheetsWriter)
     │     │       ├─ Convertir a filas: [ASIN, EAN, Title, ...]
     │     │       ├─ Append a worksheet (batch_update)
     │     │       ├─ Retry: 3 veces con backoff
     │     │       └─ Log success/failure
     │     │
     │     ├─ [2] PostgreSQL (DB Repository)
     │     │       ├─ FinancialResult → INSERT INTO results
     │     │       ├─ ShieldDrop → INSERT INTO drops
     │     │       ├─ WorkerError → INSERT INTO errors
     │     │       ├─ Retry: 3 veces con backoff
     │     │       └─ Log success/failure
     │     │
     │     └─ [3] Limpar batch buffer
     │
     └─ [FIN] Al cerrar cola (QUEUE_DONE sentinel)
              ├─ Flush último batch (< 50 registros)
              ├─ Cerrar conexiones
              └─ Print statisticas finales
```

**Google Sheets Row Format:**
```
[ASIN, EAN, Title, Brand, Buy€, BuyBox€, FBA€, Ref€, Prep€, Net€, ROI%, BSR, Cat, Top%, Seller, IsFBA, ExportedAt]
```

**DB Inserts:**
```sql
INSERT INTO results (asin, ean, title, ...) VALUES (...)
INSERT INTO drops (asin, ean, shield, reason, ...) VALUES (...)
INSERT INTO errors (ean, asin, error_message, stack_trace) VALUES (...)
```

---

## 🔌 Integraciones Externas

### SP-API (Amazon)

**Autenticación: LWA + SigV4**
```
1. Client obtiene Access Token de LWA:
   POST https://api.amazon.com/auth/o2/token
   └─ Parámetros: grant_type, refresh_token, client_id, client_secret
   └─ Response: access_token, expires_in

2. Cada request es firmado con SigV4:
   ├─ Canonical Request (method, path, query, headers, payload)
   ├─ String to Sign (con Timestamp)
   ├─ Signature (HMAC-SHA256 con aws_secret_key)
   └─ Authorization header con Signature
```

**Rate Limiting:**
```
Token Bucket por endpoint:
├─ searchCatalogItems: 5 burst, 1 token/seg
├─ getItemOffers: 5 burst, 1 token/seg
├─ getCompetitivePricing: 5 burst, 1 token/seg
├─ getMyFeesEstimate: 1 burst, 1 token/seg
└─ getListingsRestrictions: 5 burst, 1 token/seg (2 seg de throttle)
```

### Keepa

**Análisis de Masacres:**
```
GET https://api.keepa.com/product/
Parámetros: asin, domain, history

Lógica de detección:
├─ Obtener histórico de 90 días
├─ Contar vendedores FBA por día
├─ Calcular max drop en 24h: (sellers_T0 - sellers_T1) / sellers_T0
└─ Si drop >= 80% → Massacre detected
```

### Google Sheets

**Setup:**
```
1. Crear Service Account en GCP
2. Descargar JSON credentials
3. Guardar en: credentials/google_service_account.json
4. Compartir spreadsheet con email de SA
```

**Operaciones:**
```
gspread_asyncio.AsyncioGspreadClientManager
├─ authorize() → Google API client
├─ open_by_key(spreadsheet_id) → Spreadsheet
├─ worksheet('Resultados') → Worksheet
├─ append_rows(values) → Batch update (50 filas)
└─ Retry con backoff en errores 429, 5xx
```

---

## 🧠 Patrones de Diseño

### 1. **Async/Await + asyncio.Queue**
- Concurrencia sin threads
- Mejor manejo de I/O bound tasks (API calls)
- Pool de N workers escalable

### 2. **Token Bucket Rate Limiter**
- Permite ráfagas cortas (burst=5)
- Luego throttle a 1 req/seg
- Respeta throttle budgets de SP-API

### 3. **Fail-Closed Security Chain**
- Ante cualquier error inesperado → descarta
- No permite "saltar" escudos
- Prefiere falso positivo a falso negativo

### 4. **Caché Redis (7 días)**
- Evita resolver el mismo EAN múltiples veces
- Trade-off: ASINs pueden cambiar, pero raro
- TTL de 7 días es buen balance

### 5. **Batch Processing**
- Google Sheets: 50 rows por batch (mejor rendimiento)
- Reduce API calls
- Transacciones más eficientes en DB

### 6. **Structured Logging**
- Cada evento tiene contexto (asin, ean, worker_id, etc.)
- Logs JSON en producción (ELK, CloudWatch)
- Fácil de debuggear y auditar

---

## 📊 Data Models

### ProductInput (Entrada)
```python
@dataclass(frozen=True, slots=True)
class ProductInput:
    ean: str          # Identificador de producto
    buy_price: float  # Precio de compra
    source_row: int   # Nº de fila en CSV (para trazabilidad)
```

### ResolvedProduct (Tras EAN Resolver)
```python
@dataclass(slots=True)
class ResolvedProduct:
    ean: str
    asin: str
    title: str
    brand: str
    buy_price: float
    sales_ranks: list[dict]  # [{"rank": 42, "category": "Cat"}]
    source_row: int
```

### EnrichedProduct (Tras Shields - si PASS)
```python
# (Extendiendo ResolvedProduct)
├─ buybox_price: float
├─ buybox_seller_name: str
├─ buybox_is_fba: bool
├─ category_id: str
└─ [datos de validación de shields]
```

### FinancialResult (Tras Calculator - si APROBADO)
```python
@dataclass(slots=True, frozen=True)
class FinancialResult:
    asin: str
    ean: str
    title: str
    brand: str
    source_row: int
    buy_price: float
    buybox_price: float
    fees: FeeBreakdown  # {fba_fee, referral_fee, prep_shipping}
    net_profit: float
    roi_pct: float
    bsr_rank: int
    bsr_category: str
    bsr_category_size: int
    bsr_top_pct: float
    buybox_seller_name: str
    buybox_is_fba: bool
```

### ShieldDrop (Descartado)
```python
{
    "type": "shield_drop",
    "asin": "B07XYZ123",
    "ean": "5901234123457",
    "shield": "keepa_massacre",  # ean_resolver, blacklist, amazon_bb, brand_bb, keepa_massacre, gating
    "reason": "Caída del 85% en vendedores FBA"
}
```

---

## ⚙️ Configuración y Settings

**Fuente:** `src/core/config.py`

```python
settings = Settings()  # Singleton

# Credenciales (de .env)
├─ sp_api_refresh_token: SecretStr
├─ sp_api_client_id: SecretStr
├─ sp_api_client_secret: SecretStr
├─ aws_access_key_id: SecretStr
├─ aws_secret_access_key: SecretStr
├─ keepa_api_key: SecretStr
├─ google_credentials_json_path: str

# URLs
├─ sp_api_endpoint: str (https://sellingpartnerapi-eu.amazon.com)
├─ database_url: str (postgresql+asyncpg://...)
├─ redis_url: str (redis://localhost:6379/0)

# Pipeline
├─ min_roi_pct: float (20.0)
├─ bsr_top_pct: float (2.0)
├─ prep_shipping_fixed: float (0.50)
├─ pipeline_concurrency: int (10)

# Google Sheets
└─ google_sheets_id: str
```

---

## 🔍 Error Handling

**Estrategia general:**
```
Try:
  ├─ Known exception → Log warning + Descarta (no bloquea)
  └─ Unknown exception → Log error + stack trace + Descarta

Result:
  └─ Pipeline NUNCA se para (resiliente)
```

**Exceptions Custom:**
```
FBABotBaseError (raíz)
├─ SPAPIAuthError → 401/403 LWA
├─ SPAPIRateLimitError → 429 (retry)
├─ SPAPINotFoundError → 404 ASIN
├─ SPAPIServerError → 5xx (retry)
├─ KeepaAPIError → Error Keepa
└─ PipelineDropError → Descartado por shield
```

---

## 📈 Métricas de Pipeline

**Estadísticas finales (stdout):**
```
Pipeline Summary
════════════════════════════════════════════
Total Processed:    1500 products
✓ Approved:         1200 (80.0%)
✗ Dropped:          300  (20.0%)
⚠️  Errors:          5    (0.3%)

Duration:           12m 45s
Throughput:         ~2 products/sec

Drops by Shield:
  ├─ ean_resolver:  45 (15%)
  ├─ blacklist:     30 (10%)
  ├─ amazon_bb:     50 (17%)
  ├─ brand_bb:      75 (25%)
  ├─ keepa_massacre: 80 (27%)
  └─ gating:        20 (7%)

Exported:
  ├─ Google Sheets: 1200 rows
  └─ PostgreSQL:    1500 records (1200 results + 300 drops)
════════════════════════════════════════════
```

---

**Fin de ARCHITECTURE.md**
