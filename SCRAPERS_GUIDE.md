# SCRAPERS_GUIDE.md - Guía de Uso de Scrapers

## 📋 Tabla de Contenidos

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Módulos](#módulos)
4. [Ejemplos de Uso](#ejemplos-de-uso)
5. [Integración con Pipeline](#integración-con-pipeline)
6. [Mejores Prácticas](#mejores-prácticas)

---

## 🎯 Overview

**Antes:** Bot solo analizaba productos (CSV input)  
**Ahora:** Bot también DESCUBRE productos automáticamente

### Tres Formas de Usar el Bot

```
1️⃣  CSV Manual Input
    └─ Tradicional: Tú das CSV → Bot analiza

2️⃣  Keyword Scraping
    └─ Nuevo: Buscas keywords → Bot genera CSV → Bot analiza

3️⃣  Competitor Analysis
    └─ Nuevo: Das seller IDs → Bot scrapa → Bot analiza

4️⃣  Continuous Monitoring
    └─ Nuevo: Bot monitorea precios/BSR continuamente
```

---

## 🚀 Quick Start

### 1. Buscar por Keywords

```python
import asyncio
from src.main import run_scraper_by_keywords, run_pipeline

async def main():
    # Paso 1: Buscar productos
    csv = await run_scraper_by_keywords(
        keywords=["gaming mouse", "mechanical keyboard", "usb-c cable"],
        output_csv="data/gaming_products.csv",
        max_results=100
    )
    
    # Paso 2: Analizar viabilidad
    stats = await run_pipeline(csv)
    
    print(f"✓ {stats['pass']} productos viables")

asyncio.run(main())
```

### 2. Analizar Competencia

```python
# Buscar productos de competidores
csv = await run_scraper_analyze_competitors(
    competitor_seller_ids=["AXXXXXXXXXXXXX", "BXXXXXXXXXXXXX"],
    output_csv="data/competitor_products.csv"
)

# Luego pasar al pipeline
stats = await run_pipeline(csv)
```

### 3. Discovery Completo

```python
# Keywords + Competencia
csv = await run_full_discovery(
    keywords=["gaming mouse", "keyboard"],
    competitor_ids=["AXXXXXXXXXXXXX"],
    output_csv="data/full_discovery.csv"
)

stats = await run_pipeline(csv)
```

### 4. Monitoreo Continuo

```python
# Monitorear ASINs cada 30 minutos durante 24 horas
await run_monitoring(
    watchlist_asins=["B07XYZ123", "B08ABC456", "B09DEF789"],
    check_interval_minutes=30,
    duration_hours=24
)
```

---

## 🔧 Módulos

### 1. **KeywordScraper**

Busca keywords en Keepa y extrae productos viables.

#### Métodos

```python
async def search_keyword(
    keyword: str,
    max_results: int = 50,
    min_bsr: Optional[int] = None,
    max_price: Optional[float] = None
) -> AsyncIterator[ScrapedProduct]:
```

#### Ejemplo

```python
from src.scrapers import KeywordScraper
from src.api.keepa_client import KeepaClient

scraper = KeywordScraper(keepa_client)

async for product in scraper.search_keyword(
    keyword="gaming mouse",
    max_results=30,
    min_bsr=5000,  # Top 1%
    max_price=50,  # Max €50
):
    print(f"{product.asin}: {product.title}")
    print(f"  Price: €{product.current_price}")
    print(f"  BSR: {product.bsr_rank}")
    print(f"  Estimated Buy Price: €{product.estimated_buy_price}")
```

#### Data Class

```python
@dataclass(slots=True, frozen=True)
class ScrapedProduct:
    asin: str
    title: str
    brand: str
    current_price: float           # Precio actual en Amazon
    estimated_buy_price: float     # Lo que tendrías que comprar
    bsr_rank: int                  # BSR en categoría
    bsr_category: str
    review_count: int
    rating: float
    data_source: str               # 'keyword_search', 'competitor', etc.
```

---

### 2. **CompetitorScraper**

Analiza productos de competidores.

#### Métodos

```python
async def analyze_competitors(asin: str) -> Optional[CompetitorAnalysis]:
    """Analiza competidores de un ASIN"""

async def analyze_seller(
    seller_id: str,
    max_asins: int = 50
) -> AsyncIterator[ScrapedProduct]:
    """Obtiene productos de un seller"""

async def find_pricing_gaps(
    category: str,
    marketplace: str = "ES"
) -> AsyncIterator[dict]:
    """Identifica gaps de precios en categoría"""
```

#### Ejemplo

```python
from src.scrapers import CompetitorScraper

scraper = CompetitorScraper(sp_client, keepa_client)

# Analizar competencia de un ASIN
analysis = await scraper.analyze_competitors("B07XYZ123")

if analysis:
    print(f"Avg Competitor Price: €{analysis.competitor_price}")
    print(f"Our Threshold: €{analysis.our_price_threshold}")
    print(f"Price Advantage: €{analysis.price_advantage}")
```

---

### 3. **PriceMonitor**

Monitorea precios y BSR continuamente.

#### Métodos

```python
async def add_to_watchlist(asins: list[str]) -> None:
    """Agrega ASINs a monitoreo"""

async def check_watchlist() -> list[PriceAlert]:
    """Chequea todos y genera alertas"""

async def get_historical_data(asin: str, days: int = 30) -> list[PriceSnapshot]:
    """Obtiene histórico de precios"""
```

#### Alertas Detectadas

```
- "price_drop"         → Caída >= 10%
- "price_surge"        → Aumento >= 15%
- "bsr_improvement"    → BSR mejoró >= 20%
- "restock_detected"   → Stock aumentó significativamente
```

#### Ejemplo

```python
from src.scrapers import PriceMonitor

monitor = PriceMonitor(sp_client, keepa_client, redis)

# Agregar a watchlist
await monitor.add_to_watchlist(["B07XYZ123", "B08ABC456"])

# Chequear periódicamente
alerts = await monitor.check_watchlist()

for alert in alerts:
    print(f"{alert.alert_type}: {alert.asin}")
    print(f"  Change: {alert.change_pct:.1f}%")
    print(f"  Action: {alert.action_suggested}")
```

---

### 4. **ScraperOrchestrator**

Coordina todos los scrapers y genera CSVs.

#### Métodos

```python
async def scrape_keywords(keywords: list[str]) -> AsyncIterator[ScrapedProduct]:
    """Busca keywords"""

async def scrape_and_generate_csv(
    keywords: list[str] | None = None,
    competitor_asins: list[str] | None = None,
    output_path: str | Path = "data/discovered_products.csv"
) -> Path:
    """Discovery completo + genera CSV"""

async def start_monitoring(watchlist_asins: list[str]) -> None:
    """Inicia monitoreo indefinido"""

async def get_recommendations() -> list[dict]:
    """Obtiene recomendaciones basadas en monitoring"""
```

---

## 💡 Ejemplos de Uso

### Ejemplo 1: Descubrir Gaming Peripherals

```python
async def find_gaming_products():
    keywords = [
        "gaming mouse",
        "mechanical keyboard",
        "gaming headset",
        "mouse pad",
        "gaming chair",
    ]
    
    csv = await run_scraper_by_keywords(
        keywords=keywords,
        max_results=150,
        output_csv="data/gaming_discovery.csv"
    )
    
    # Analizar
    stats = await run_pipeline(csv)
    
    print(f"Descubiertos: {len(keywords) * 30} productos")
    print(f"Viables: {stats['pass']} productos")
    print(f"ROI promedio: {stats.get('avg_roi', 'N/A')}%")

asyncio.run(find_gaming_products())
```

### Ejemplo 2: Analizar Competencia de Amazon ES

```python
async def analyze_es_competitors():
    # Seller IDs principales en ES
    sellers = [
        "A1XXXXXXXXXXXXX",  # Vendedor 1
        "A2XXXXXXXXXXXXX",  # Vendedor 2
        "A3XXXXXXXXXXXXX",  # Vendedor 3
    ]
    
    csv = await run_scraper_analyze_competitors(
        competitor_seller_ids=sellers,
        output_csv="data/competitors_es.csv"
    )
    
    # Pasar al pipeline
    stats = await run_pipeline(csv)

asyncio.run(analyze_es_competitors())
```

### Ejemplo 3: Discovery + Competencia Combinados

```python
async def full_discovery():
    keywords = ["usb-c cable", "wireless charger", "power bank"]
    competitors = ["A1XXXXXXXXXXXXX", "A2XXXXXXXXXXXXX"]
    
    csv = await run_full_discovery(
        keywords=keywords,
        competitor_ids=competitors,
        output_csv="data/combined_discovery.csv"
    )
    
    # Pasar al pipeline
    stats = await run_pipeline(csv)
    
    print(f"Total descubiertos: {stats['total']}")
    print(f"Aprobados: {stats['pass']}")
    print(f"Descartados: {stats['drop']}")

asyncio.run(full_discovery())
```

### Ejemplo 4: Monitoreo Inteligente

```python
async def monitor_opportunities():
    # ASINs actuales en portfolio
    portfolio_asins = [
        "B07ABC123",
        "B08DEF456",
        "B09GHI789",
    ]
    
    # Monitorear por 72 horas
    await run_monitoring(
        watchlist_asins=portfolio_asins,
        check_interval_minutes=30,
        duration_hours=72
    )

asyncio.run(monitor_opportunities())
```

---

## 🔗 Integración con Pipeline

### Flujo Completo: Discovery → Analysis → Export

```
┌─────────────────────────────────────────┐
│  1. DISCOVERY (Scraper)                 │
├─────────────────────────────────────────┤
│ • Buscar keywords                       │
│ • Analizar competencia                  │
│ • Extraer 200+ ASINs                    │
└──────────┬──────────────────────────────┘
           │ Genera: data/discovered.csv
           ▼
┌─────────────────────────────────────────┐
│  2. ANALYSIS (Pipeline)                 │
├─────────────────────────────────────────┤
│ • EAN Resolver (usar ASIN)              │
│ • Shield Chain (validación)             │
│ • Financial Calc (ROI)                  │
└──────────┬──────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────┐
│  3. EXPORT                              │
├─────────────────────────────────────────┤
│ • ✓ Viables → Google Sheets            │
│ • ✗ Descartados → PostgreSQL            │
└─────────────────────────────────────────┘
```

### Script Completo

```python
import asyncio
from src.main import run_scraper_by_keywords, run_pipeline

async def main():
    print("📍 Fase 1: Descubrimiento de Productos")
    csv = await run_scraper_by_keywords(
        keywords=[
            "gaming mouse",
            "mechanical keyboard",
            "usb-c cable",
            "portable charger",
            "wireless speaker",
        ],
        max_results=200
    )
    print(f"✓ CSV generado: {csv}")
    
    print("\n📍 Fase 2: Análisis de Viabilidad")
    stats = await run_pipeline(csv)
    
    print("\n📊 RESULTADOS:")
    print(f"  Total Procesados: {stats['total']}")
    print(f"  ✓ Viables: {stats['pass']} ({stats['pass']/stats['total']*100:.1f}%)")
    print(f"  ✗ Descartados: {stats['drop']}")
    print(f"  ⚠️  Errores: {stats['errors']}")
    
    print("\n📈 Próximos pasos:")
    print("  1. Revisar en Google Sheets")
    print("  2. Validar precios de compra")
    print("  3. Proceder con compras")

asyncio.run(main())
```

---

## 📋 Mejores Prácticas

### 1. Usar Keywords Específicos

❌ Malo:
```python
keywords = ["mouse"]  # Muy genérico: 1M+ resultados
```

✅ Bueno:
```python
keywords = [
    "gaming mouse mechanical",
    "ergonomic wireless mouse",
    "bluetooth mouse compact",
]  # Específico: 10-50K resultados cada uno
```

### 2. Filtrar por BSR

```python
# Solo productos con buen BSR
async for product in scraper.search_keyword(
    keyword="gaming mouse",
    min_bsr=5000,  # Top 1% en categoría
):
    # producto viables
```

### 3. Rate Limiting

```python
# Keepa tiene límites, dejar espacio entre búsquedas
keywords = ["mouse", "keyboard", "headphone"]

for keyword in keywords:
    products = await scraper.search_keyword(keyword)
    await asyncio.sleep(5)  # Esperar 5s entre keywords
```

### 4. Batch Processing

```python
# En lugar de procesar 1 producto:
# Procesar lotes de 50

products = []
async for product in scraper.batch_search(keywords):
    products.append(product)
    
    if len(products) >= 50:
        await exporter.export_batch(products)
        products = []
```

### 5. Monitoreo Programado

```python
# Usar cron/scheduler para ejecutar regularmente
# Opción 1: APScheduler

from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('cron', hour=9, minute=0)
async def daily_discovery():
    csv = await run_scraper_by_keywords(["gaming mouse"])
    stats = await run_pipeline(csv)
    # Enviar notificación

scheduler.start()
```

---

## 🔒 Limitaciones y Consideraciones

### Rate Limits

| API | Límite | Espera |
|-----|--------|--------|
| Keepa | 100 req/min | 0.6s entre req |
| SP-API | Variable | Token bucket |
| Google Sheets | 300 req/min | Batch 50 filas |

### Recomendaciones

1. **Máximo 300 productos por discovery** (tarda ~30-45 min)
2. **Monitoreo cada 30+ minutos** (evitar rate limits)
3. **Keywords específicas** (20-50 keywords máximo por sesión)
4. **Competencia limitada** (5-10 sellers máximo)

---

## 🎓 Preguntas Frecuentes

**¿Puedo buscar todos los keywords a la vez?**
Sí, pero respeta rate limits. Máximo 50 keywords por sesión.

**¿Cómo monitoreamos 100 ASINs?**
Dividir en lotes de 20-30, rotar cada 30 minutos.

**¿Qué pasa si un scraper falla?**
Se registra el error, continúa con el siguiente. El pipeline no se detiene.

**¿Puedo combinar discovery + análisis en pipeline?**
Sí, exactamente para eso está la integración. Ver ejemplo completo arriba.

**¿Cuánta información me lleva?**
- 200 productos: ~500 MB (datos en memoria)
- Google Sheets: Automático (sin límite de almacenamiento)
- PostgreSQL: 1-2 GB para años de historial

---

## 🚀 Próximos Pasos

1. ✅ Ejecutar keyword scraping
2. ✅ Pasar CSV al pipeline
3. ✅ Revisar resultados
4. ✅ Monitorear top 20 viables
5. ⏳ Automatizar discovery (scheduler)
6. ⏳ Dashboard de monitoreo
7. ⏳ ML: Predictor de demanda

---

**¡Felicidades! Ya tienes un sistema de discovery automático. 🎉**

Puedes empezar con:
```python
await run_scraper_by_keywords(["gaming mouse", "keyboard"])
```

¿Preguntas o problemas? Revisar DEPLOYMENT_AND_TROUBLESHOOTING.md
