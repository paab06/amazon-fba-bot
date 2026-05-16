# API_REFERENCE.md - Referencia Técnica de Módulos

## 📚 Tabla de Módulos

| Módulo | Propósito | Dependencias |
|--------|-----------|--------------|
| `src.main` | Orquestador principal | asyncio, tqdm |
| `src.pipeline.ingestor` | Lectura CSV | aiofiles |
| `src.pipeline.ean_resolver` | EAN→ASIN | sp_api, redis |
| `src.pipeline.shields` | Validación seguridad | keepa, sp_api |
| `src.pipeline.financial_calc` | Cálculo rentabilidad | json (local files) |
| `src.pipeline.exporter` | Persistencia | gspread_asyncio, asyncpg |
| `src.api.sp_api_client` | Cliente SP-API | aiohttp, tenacity |
| `src.api.keepa_client` | Cliente Keepa | aiohttp |
| `src.api.google_sheets_client` | Cliente Google Sheets | gspread_asyncio |
| `src.core.config` | Configuración | pydantic_settings |
| `src.core.rate_limiter` | Rate limiting | asyncio, time |
| `src.core.logger` | Logging | structlog |
| `src.core.exceptions` | Excepciones custom | - |
| `src.db.repository` | Data access | asyncpg |

---

## 🔧 Módulos Detallados

### src/main.py

**Punto de Entrada Principal**

```python
async def run_pipeline(csv_path: str | Path) -> dict:
    """
    Ejecuta el pipeline completo.
    
    Args:
        csv_path: Ruta a archivo CSV con EANs
        
    Returns:
        dict con estadísticas:
        {
            "total_processed": 1500,
            "approved": 1200,
            "dropped": 300,
            "errors": 5,
            "duration_seconds": 765.3,
            "throughput_per_sec": 1.96
        }
    """
    # Implementación...
```

**Worker Loop**
```python
async def _worker_loop(
    worker_id: int,
    ingest_queue: asyncio.Queue,
    results_queue: asyncio.Queue,
    resolver: EANResolver,
    shield_chain: ShieldChain,
    calculator: FinancialCalculator,
    progress: tqdm,
    shutdown_event: asyncio.Event,
) -> None:
    """
    Loop de un worker consumiendo ingest_queue.
    
    Características:
    - Non-blocking queue.get_nowait()
    - Reintenta si cola vacía (sleep 0.1s)
    - Chequea shutdown_event regularmente
    """
```

---

### src/pipeline/ingestor.py

**Interfaz Pública**

```python
async def read_csv(path: str | Path) -> AsyncIterator[ProductInput]:
    """
    Generador asíncrono que lee CSV y emite ProductInput.
    
    Args:
        path: Ruta a archivo CSV
        
    Yields:
        ProductInput(ean, buy_price, source_row)
        
    Raises:
        FileNotFoundError: Si CSV no existe
        ValueError: Si columnas requeridas no existen
        
    Ejemplo:
        async for product in read_csv("input.csv"):
            print(f"EAN: {product.ean}, Price: {product.buy_price}")
            
    Validaciones:
    - EAN no vacío
    - Precio > 0
    - Precio es número válido
    """
```

**Data Class**
```python
@dataclass(frozen=True, slots=True)
class ProductInput:
    """Entrada mínima del pipeline"""
    ean: str              # Código EAN/UPC
    buy_price: float      # Precio de compra (€)
    source_row: int       # Número de fila en CSV (para trazabilidad)
```

---

### src/pipeline/ean_resolver.py

**EANResolver Class**

```python
class EANResolver:
    """Resuelve EAN→ASIN con caché Redis"""
    
    def __init__(self, sp_client: SPAPIClient, redis: Redis) -> None:
        """
        Args:
            sp_client: Cliente SP-API para consultas
            redis: Conexión Redis para caché
        """
    
    async def resolve(self, product_input: ProductInput) -> Optional[ResolvedProduct]:
        """
        Resuelve un EAN a ASIN.
        
        Args:
            product_input: ProductInput con EAN
            
        Returns:
            ResolvedProduct si encontrado
            None si no hay resultado o error (descarta silenciosamente)
            
        Flujo:
        1. Consulta Redis (TTL 7 días)
        2. Si no encuentra, llama SP-API searchCatalogItems
        3. Si múltiples resultados, selecciona mejor BSR
        4. Cachea en Redis
        5. Retorna ResolvedProduct
        """
```

**ResolvedProduct Data Class**
```python
@dataclass(slots=True)
class ResolvedProduct:
    """Producto con identidad Amazon confirmada"""
    ean: str
    asin: str           # Identificador Amazon (10 chars)
    title: str
    brand: str
    buy_price: float
    sales_ranks: list[dict]  # [{"rank": 42, "category": "Electrónica"}]
    source_row: int
```

---

### src/pipeline/shields.py

**ShieldBase (Interfaz)**

```python
class ShieldBase(ABC):
    """Clase base para todos los escudos"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre del escudo (ej: 'blacklist', 'gating')"""
    
    @abstractmethod
    async def check(self, product: ResolvedProduct) -> None:
        """
        Valida el producto.
        
        Args:
            product: Producto a validar
            
        Raises:
            PipelineDropError: Si producto no pasa validación
            
        Returns:
            None implícitamente si pasa
        """
```

**Escudos Implementados**

1. **BrandBlacklistShield**
   ```python
   # Carga data/brand_blacklist.json
   # Compara: product.brand (case-insensitive)
   # DROP si: brand en blacklist
   ```

2. **AmazonBuyBoxShield**
   ```python
   # Verifica: product.buybox_seller_name
   # DROP si: seller ∈ {Amazon, Amazon EU, Warehouse Deals}
   ```

3. **BrandBuyBoxShield**
   ```python
   # Verifica: brand == buybox_seller_name
   # DROP si: no match
   ```

4. **KeepaCliffDetectorShield**
   ```python
   # Llama Keepa API
   # Analiza: historial 90 días
   # DROP si: caída >= 80% vendedores FBA
   ```

5. **GatingShield**
   ```python
   # Llama SP-API getListingsRestrictions
   # Verifica: gating restrictions
   # DROP si: requiere aprobación especial
   ```

**ShieldChain Class**

```python
class ShieldChain:
    """Ejecuta todos los escudos en serie"""
    
    def __init__(self, shields: list[ShieldBase]) -> None:
        """
        Args:
            shields: Lista de shields en orden (menor a mayor coste)
        """
    
    async def run(self, product: ResolvedProduct) -> ShieldResult:
        """
        Ejecuta todos los escudos.
        
        Returns:
            ShieldResult {
                passed: bool,
                drop_shield: str | None,
                drop_reason: str | None,
                product: EnrichedProduct | None
            }
            
        Si uno falla → retorna inmediatamente
        """
```

**ShieldResult Data Class**
```python
@dataclass
class ShieldResult:
    passed: bool
    drop_shield: str | None     # Nombre del escudo que lo descartó
    drop_reason: str | None     # Razón del descarte
    product: Optional[EnrichedProduct]  # Si passed=True
```

---

### src/pipeline/financial_calc.py

**FinancialCalculator Class**

```python
class FinancialCalculator:
    """Calcula rentabilidad y valida criterios de exportación"""
    
    def __init__(self, sp_client: SPAPIClient) -> None:
        """
        Args:
            sp_client: Cliente SP-API para obtener fees
        """
    
    async def evaluate(self, product: EnrichedProduct) -> Union[FinancialResult, FinancialDropReason]:
        """
        Calcula financials y valida criterios.
        
        Args:
            product: Producto enriquecido (tras shields)
            
        Returns:
            FinancialResult si APROBADO
            FinancialDropReason si DESCARTADO
            
        Cálculos:
        1. Obtener FBA fees de SP-API
        2. Calcular beneficio neto = buybox - (buy + fees)
        3. Calcular ROI% = (benefit / buy) * 100
        4. Validar ROI >= min_roi_pct
        5. Validar BSR en top N%
        """
```

**FeeBreakdown Data Class**
```python
@dataclass(slots=True, frozen=True)
class FeeBreakdown:
    """Desglose de costes"""
    fba_fee: float              # Comisión FBA Amazon
    referral_fee: float         # Comisión de referencia
    prep_shipping: float        # Preparación + envío fijo
    
    @property
    def total(self) -> float:
        """Total fees"""
```

**FinancialResult Data Class**
```python
@dataclass(slots=True, frozen=True)
class FinancialResult:
    """Producto APROBADO con análisis financiero"""
    # Identidad
    asin: str
    ean: str
    title: str
    brand: str
    source_row: int
    
    # Precios
    buy_price: float
    buybox_price: float
    
    # Fees
    fees: FeeBreakdown
    
    # Resultados
    net_profit: float
    roi_pct: float
    
    # BSR
    bsr_rank: int
    bsr_category: str
    bsr_category_size: int
    bsr_top_pct: float       # Percentil en categoría
    
    # Vendedor
    buybox_seller_name: str
    buybox_is_fba: bool
```

---

### src/api/sp_api_client.py

**SPAPIClient Class**

```python
class SPAPIClient:
    """Cliente SP-API (Selling Partner API)"""
    
    async def search_catalog_items(self, ean: str) -> list[dict]:
        """
        Busca ASIN por EAN.
        
        Args:
            ean: Código EAN/UPC
            
        Returns:
            [{"asin": "B07...", "title": "...", "brand": "..."}, ...]
            
        Raises:
            SPAPINotFoundError: Si no hay resultados
            SPAPIRateLimitError: 429
            SPAPIServerError: 5xx
        """
    
    async def get_item_offers(self, asin: str, condition: str = "New") -> dict:
        """
        Obtiene precios y vendedores.
        
        Returns:
            {
                "buybox_price": 24.99,
                "buybox_seller_name": "Brand Name",
                "buybox_is_fba": True,
                "offers": [...]
            }
        """
    
    async def get_my_fees_estimate(self, asin: str, price: float, msku: str) -> dict:
        """
        Estima fees FBA.
        
        Returns:
            {
                "fba_fee": 5.00,
                "referral_fee": 3.75,
                "variable_closing_fee": 0.00
            }
        """
    
    async def get_listings_restrictions(self, asin: str) -> dict:
        """
        Obtiene restricciones (gating).
        
        Returns:
            {
                "restricted": bool,
                "reasons": ["reason1", "reason2"]
            }
        """
```

**LWATokenManager (Interno)**
```python
class LWATokenManager:
    """Gestiona tokens OAuth2 de Login with Amazon"""
    
    async def get_token(self, session: aiohttp.ClientSession) -> str:
        """
        Obtiene access token válido.
        Refresca automáticamente si está próximo a expirar.
        
        Thread-safe: asyncio.Lock
        """
```

**RateLimiter (Interno)**
```python
class RateLimiter:
    """Token bucket para respetar throttle budgets SP-API"""
    
    async def acquire(self, tokens: float = 1.0) -> None:
        """
        Adquiere tokens del bucket.
        Espera si no hay suficientes.
        """
```

---

### src/api/keepa_client.py

**KeepaClient Class**

```python
class KeepaClient:
    """Cliente para Keepa API (análisis de precios)"""
    
    async def check_fba_massacre(self, asin: str, days: int = 90) -> dict:
        """
        Detecta caída de vendedores FBA.
        
        Args:
            asin: Identificador Amazon
            days: Ventana de análisis (default 90 días)
            
        Returns:
            {
                "massacre_detected": bool,
                "max_drop_pct": 85.0,
                "fba_sellers_before": 42,
                "fba_sellers_after": 6
            }
        """
    
    async def get_category_tree(self) -> dict:
        """Obtiene árbol de categorías Amazon"""
```

---

### src/api/google_sheets_client.py

**SheetsWriter Class**

```python
class SheetsWriter:
    """Exporta datos a Google Sheets"""
    
    async def setup(self) -> None:
        """Inicializa conexión y asegura cabecera"""
    
    async def append_rows(self, rows: list[list]) -> None:
        """
        Añade filas al spreadsheet.
        
        Args:
            rows: [[col1, col2, ...], ...]
            
        Features:
        - Batching automático (50 rows)
        - Retry con backoff
        - Timestamps automáticos
        """
```

---

### src/core/config.py

**Settings Class**

```python
class Settings(BaseSettings):
    """Configuración centralizada (Pydantic)"""
    
    # SP-API
    sp_api_refresh_token: SecretStr
    sp_api_client_id: SecretStr
    sp_api_client_secret: SecretStr
    sp_api_seller_id: str
    sp_api_marketplace_id: str  # default: A1RKKUPIHCS9HS (Spain)
    sp_api_region: str          # default: eu-west-1
    sp_api_endpoint: str
    
    # AWS (para SigV4)
    aws_access_key_id: SecretStr
    aws_secret_access_key: SecretStr
    aws_role_arn: str
    
    # Keepa
    keepa_api_key: SecretStr
    
    # Database
    database_url: str
    
    # Redis
    redis_url: str
    
    # Pipeline
    min_roi_pct: float              # default: 20.0
    bsr_top_pct: float              # default: 2.0
    prep_shipping_fixed: float      # default: 0.50
    pipeline_concurrency: int       # default: 10
    
    # Google Sheets
    google_sheets_id: str
    google_credentials_json_path: str

# Singleton global
settings = Settings()
```

**Uso:**
```python
from src.core.config import settings

print(settings.min_roi_pct)  # 20.0
print(settings.pipeline_concurrency)  # 10
```

---

### src/core/rate_limiter.py

**RateLimiter Class**

```python
class RateLimiter:
    """Token bucket asíncrono"""
    
    def __init__(self, rate: float, burst: int, name: str = "default") -> None:
        """
        Args:
            rate: Tokens añadidos por segundo (ej: 1.0 = 1 token/seg)
            burst: Capacidad máxima del bucket (ej: 5)
            name: Nombre para logging
            
        Ejemplo (SP-API searchCatalogItems):
            limiter = RateLimiter(rate=1.0, burst=5, name="searchCatalogItems")
            await limiter.acquire()  # Espera si es necesario
        """
    
    async def acquire(self, tokens: float = 1.0) -> None:
        """
        Adquiere tokens del bucket.
        Si no hay suficientes, espera.
        
        Thread-safe: asyncio.Lock
        """
```

---

### src/core/logger.py

**Setup Logging**

```python
def setup_logging(level: str = "INFO") -> None:
    """
    Configura structlog.
    
    Args:
        level: DEBUG, INFO, WARNING, ERROR
        
    Desarrollo: ConsoleRenderer (legible)
    Producción: JSONRenderer (máquina-readable)
    
    Ejemplo:
        setup_logging("DEBUG")
        log = structlog.get_logger(__name__)
        log.info("event", key="value", another=123)
    """
```

**Output Ejemplo:**
```json
{
  "timestamp": "2024-05-15T14:30:52.123Z",
  "level": "INFO",
  "logger": "src.pipeline.ean_resolver",
  "event": "ean_resolver.start",
  "ean": "5901234123457",
  "row": 2
}
```

---

### src/core/exceptions.py

**Exception Hierarchy**

```python
FBABotBaseError (base)
├─ SPAPIAuthError        # 401/403 LWA
├─ SPAPIRateLimitError   # 429 (retry)
├─ SPAPINotFoundError    # 404
├─ SPAPIServerError      # 5xx
├─ KeepaAPIError         # Error Keepa
└─ PipelineDropError     # Descartado por shield
    └─ args: (asin, shield, reason)
```

**Uso:**
```python
try:
    await sp_api.search_catalog_items(ean)
except SPAPINotFoundError:
    log.warning("asin_not_found", ean=ean)
except SPAPIRateLimitError:
    log.warning("rate_limited, retrying...")
    await asyncio.sleep(backoff)
```

---

### src/db/repository.py

**Repository Pattern (Pendiente de Implementación)**

```python
class ProductRepository:
    """Data access layer para resultados"""
    
    async def insert_result(self, result: FinancialResult) -> None:
        """Inserta en tabla results"""
    
    async def insert_drop(self, drop_info: dict) -> None:
        """Inserta en tabla drops"""
    
    async def get_by_asin(self, asin: str) -> Optional[FinancialResult]:
        """Obtiene resultado por ASIN"""
    
    async def get_top_by_roi(self, limit: int = 10) -> list[FinancialResult]:
        """Top 10 productos por ROI"""
```

---

## 🔗 Flujos de Uso Comun

### Ejemplo 1: Ejecutar Pipeline Completo

```python
import asyncio
from src.main import run_pipeline

async def main():
    stats = await run_pipeline("data/input.csv")
    print(f"Processed: {stats['total_processed']}")
    print(f"Approved: {stats['approved']}")

asyncio.run(main())
```

### Ejemplo 2: Resolver EAN Individuales

```python
from src.api.sp_api_client import SPAPIClient
from src.pipeline.ean_resolver import EANResolver, ProductInput
from redis.asyncio import from_url

async def main():
    sp_client = SPAPIClient()
    redis = await from_url("redis://localhost")
    resolver = EANResolver(sp_client, redis)
    
    product_input = ProductInput(ean="5901234123457", buy_price=12.50, source_row=2)
    resolved = await resolver.resolve(product_input)
    
    if resolved:
        print(f"ASIN: {resolved.asin}, Title: {resolved.title}")
    else:
        print("EAN not found")

asyncio.run(main())
```

### Ejemplo 3: Validar un Producto con Shields

```python
from src.pipeline.shields import ShieldChain, BrandBlacklistShield
from src.api.keepa_client import KeepaClient
from src.api.sp_api_client import SPAPIClient

async def main():
    sp_client = SPAPIClient()
    keepa_client = KeepaClient()
    
    shields = [
        BrandBlacklistShield(),
        # ... otros shields
    ]
    
    chain = ShieldChain(shields)
    result = await chain.run(resolved_product)
    
    if result.passed:
        print("✓ Producto aprobado en shields")
    else:
        print(f"✗ Descartado por: {result.drop_shield}")

asyncio.run(main())
```

---

**Fin de API_REFERENCE.md**
