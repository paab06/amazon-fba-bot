# examples/README.md

## 📚 Ejemplos de Uso del Bot

Scripts listos para copiar y ejecutar.

### 📋 Contenido

- **scraper_usage.py** — 6 ejemplos prácticos con menú interactivo

### 🚀 Uso Rápido

```bash
# Opción 1: Menú interactivo (recomendado)
python examples/scraper_usage.py

# Opción 2: Ejecutar ejemplo específico desde Python
python -c "
import asyncio
from examples.scraper_usage import example_1_keyword_search
asyncio.run(example_1_keyword_search())
"
```

### 📖 Ejemplos Disponibles

#### 1️⃣  Búsqueda Simple por Keywords
```python
await run_scraper_by_keywords(
    keywords=["gaming mouse", "keyboard"],
    max_results=100
)
```
- **Tiempo:** 2-5 minutos
- **Resultados:** ~50-100 productos
- **Uso:** Explorar nuevas categorías

#### 2️⃣  Análisis de Competencia
```python
await run_scraper_analyze_competitors(
    competitor_seller_ids=["SELLER_ID_1", "SELLER_ID_2"]
)
```
- **Tiempo:** 3-8 minutos
- **Resultados:** 50-200 productos
- **Uso:** Entender estrategia de competidores

#### 3️⃣  Discovery Completo
```python
await run_full_discovery(
    keywords=["mouse", "keyboard"],
    competitor_ids=["SELLER_ID"]
)
```
- **Tiempo:** 10-20 minutos
- **Resultados:** 200-300 productos
- **Uso:** Análisis exhaustivo de mercado

#### 4️⃣  Monitoreo Continuo
```python
await run_monitoring(
    watchlist_asins=["B07XYZ123", "B08ABC456"],
    check_interval_minutes=30,
    duration_hours=24
)
```
- **Tiempo:** 24+ horas (configurable)
- **Actualizaciones:** Cada 30 minutos
- **Uso:** Detección de oportunidades en tiempo real

#### 5️⃣  Búsqueda Iterativa
```python
# Loop sobre múltiples keywords
for batch in keyword_batches:
    await run_scraper_by_keywords(batch)
```
- **Tiempo:** Escalable
- **Resultados:** Acumulativos
- **Uso:** Testing y validación

#### 6️⃣  Analizar CSV Existente
```python
stats = await run_pipeline("data/discovered_products.csv")
```
- **Tiempo:** 2-5 minutos
- **Uso:** Re-análisis sin re-scraping

### 📊 Flujo Recomendado

**Día 1 - Exploración**
```
1. Ejecutar Ejemplo 1 (keywords simples)
2. Revisar resultados
3. Ajustar palabras clave
```

**Día 2 - Análisis Competitivo**
```
1. Ejecutar Ejemplo 2 (competitors)
2. Comparar estrategias
3. Identificar gaps
```

**Día 3 - Discovery Total**
```
1. Ejecutar Ejemplo 3 (full discovery)
2. Analizar 300+ productos
3. Seleccionar top 20
```

**Días 4+ - Monitoreo**
```
1. Ejecutar Ejemplo 4 (monitoring)
2. Revisar alertas diarias
3. Actuar en oportunidades
```

### 🔧 Personalización

#### Cambiar Palabras Clave
```python
keywords = [
    "tu keyword 1",
    "tu keyword 2",
    "tu keyword 3",
]
```

#### Cambiar Seller IDs
```python
competitor_ids = [
    "AXXXXXXXXXXXXXXXX",  # Tu competidor 1
    "BXXXXXXXXXXXXXXXX",  # Tu competidor 2
]
```

#### Cambiar Output Path
```python
csv = await run_scraper_by_keywords(
    keywords=keywords,
    output_csv="data/my_custom_name.csv"
)
```

#### Cambiar Intervalo de Monitoreo
```python
await run_monitoring(
    watchlist_asins=asins,
    check_interval_minutes=60,  # Cada hora en vez de cada 30 min
    duration_hours=48             # 2 días en vez de 1
)
```

### 📈 Interpretar Resultados

**CSV Generado:**
- Columnas: ASIN, Título, Marca, Precio, BSR, Reviews, Rating
- Listo para pasar a `run_pipeline()`

**Stats del Pipeline:**
```
{
    'pass': 45,      # ✓ Viables (ROI > 25%)
    'drop': 155,     # ✗ Descartados (ROI bajo)
    'errors': 5,     # ⚠️  Errores en procesamiento
    'total': 205
}
```

**Success Rate:**
```
Viables = pass / total = 45 / 205 = 22%
```

### ⚠️ Limitaciones

- **Keepa API:** 100 req/min (rate limiting automático)
- **Máximo por sesión:** 300 productos (~10-15 min)
- **Monitoreo:** Máximo 100 ASINs sin aumentar intervalo
- **Google Sheets:** 300 req/min (batch de 50 filas)

### 🐛 Troubleshooting

**Error: "Redis connection refused"**
```bash
docker-compose up -d redis
```

**Error: "Keepa API key invalid"**
```bash
# Verificar en .env
cat .env | grep KEEPA
```

**Error: "SP-API token expired"**
```bash
# Regenerar token en Amazon SP-API dashboard
# Actualizar .env
# Reiniciar
```

### 📞 Ayuda

- **Guía Completa:** [SCRAPERS_GUIDE.md](../SCRAPERS_GUIDE.md)
- **API Reference:** [API_REFERENCE.md](../API_REFERENCE.md)
- **Troubleshooting:** [DEPLOYMENT_AND_TROUBLESHOOTING.md](../DEPLOYMENT_AND_TROUBLESHOOTING.md)

---

**¡Happy Scraping! 🚀**
