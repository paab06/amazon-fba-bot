# CHECKLIST_SETUP.md

## ✅ Checklist de Setup

Complete esta lista antes de usar los scrapers.

---

## 🔧 Dependencias

- [ ] Python 3.11+
  ```bash
  python --version  # Debe ser 3.11 o superior
  ```

- [ ] Redis corriendo
  ```bash
  docker-compose up -d redis
  docker-compose logs redis  # Verificar que arrancó
  ```

- [ ] PostgreSQL corriendo
  ```bash
  docker-compose up -d db
  docker-compose logs db  # Verificar que arrancó
  ```

- [ ] Paquetes Python instalados
  ```bash
  pip install -e .
  # O si está en requirements.txt:
  pip install -r requirements.txt
  ```

---

## 🔑 Credenciales

- [ ] `.env` file existe
  ```bash
  ls .env  # Debe existir
  ```

- [ ] Variable `KEEPA_API_KEY` configurada
  ```bash
  grep KEEPA_API_KEY .env
  # Debe mostrar: KEEPA_API_KEY=tu_key_aqui
  ```

- [ ] Variable `AMAZON_SP_API_KEY` configurada
  ```bash
  grep AMAZON_SP_API_KEY .env
  ```

- [ ] Variable `AMAZON_SP_API_SECRET` configurada
  ```bash
  grep AMAZON_SP_API_SECRET .env
  ```

- [ ] Variable `REDIS_URL` configurada (probablemente: `redis://localhost:6379`)
  ```bash
  grep REDIS_URL .env
  ```

- [ ] Variable `DATABASE_URL` configurada (probablemente: `postgresql://user:pass@localhost/dbname`)
  ```bash
  grep DATABASE_URL .env
  ```

---

## 📁 Estructura de Archivos

- [ ] `src/scrapers/` existe
  ```bash
  ls -la src/scrapers/
  ```

- [ ] `src/scrapers/keyword_scraper.py` existe
  ```bash
  ls src/scrapers/keyword_scraper.py
  ```

- [ ] `src/scrapers/competitor_scraper.py` existe
  ```bash
  ls src/scrapers/competitor_scraper.py
  ```

- [ ] `src/scrapers/price_monitor.py` existe
  ```bash
  ls src/scrapers/price_monitor.py
  ```

- [ ] `src/scrapers/orchestrator.py` existe
  ```bash
  ls src/scrapers/orchestrator.py
  ```

- [ ] `data/` directorio existe
  ```bash
  mkdir -p data
  ```

- [ ] `examples/` directorio existe y tiene ejemplos
  ```bash
  ls examples/
  ```

---

## 🧪 Tests Básicos

### Test 1: Importaciones

```bash
python -c "from src.scrapers import KeywordScraper"
# Debe funcionar sin errores

python -c "from src.scrapers import CompetitorScraper"
python -c "from src.scrapers import PriceMonitor"
python -c "from src.scrapers import ScraperOrchestrator"
```

- [ ] KeywordScraper importa correctamente
- [ ] CompetitorScraper importa correctamente
- [ ] PriceMonitor importa correctamente
- [ ] ScraperOrchestrator importa correctamente

### Test 2: Conexión a Redis

```bash
python -c "
import asyncio
import redis.asyncio as aioredis
from src.core.config import settings

async def test():
    r = await aioredis.from_url(settings.redis_url)
    await r.ping()
    print('✓ Redis conectado')
    await r.close()

asyncio.run(test())
"
```

- [ ] Redis conecta correctamente

### Test 3: Conexión a Keepa API

```bash
python -c "
import asyncio
from src.api.keepa_client import KeepaClient

async def test():
    client = KeepaClient()
    # Hacer una búsqueda dummy
    results = await client.search_keyword('mouse', max_results=1)
    print(f'✓ Keepa API conectó, encontró {len(results)} productos')

asyncio.run(test())
"
```

- [ ] Keepa API conecta correctamente

### Test 4: Estructura de Datos

```bash
python -c "
from src.scrapers.keyword_scraper import ScrapedProduct

product = ScrapedProduct(
    asin='B07ABC123',
    title='Test Product',
    brand='TestBrand',
    current_price=29.99,
    estimated_buy_price=15.00,
    bsr_rank=1500,
    bsr_category='Electronics',
    review_count=150,
    rating=4.5,
    data_source='test'
)

print(f'✓ ScrapedProduct creado: {product.asin}')
print(f'  Precio: {product.current_price}')
print(f'  BSR: {product.bsr_rank}')
"
```

- [ ] ScrapedProduct data class funciona

---

## 🚀 Test End-to-End

### Test Minimal (5 min)

```bash
python -c "
import asyncio
from src.main import run_scraper_by_keywords

async def test():
    csv = await run_scraper_by_keywords(
        keywords=['mouse'],
        max_results=10,
        output_csv='data/test.csv'
    )
    print(f'✓ CSV generado: {csv}')

asyncio.run(test())
"
```

- [ ] Scraper by keywords funciona

### Test Full Pipeline (10-15 min)

```bash
python -c "
import asyncio
from src.main import run_scraper_by_keywords, run_pipeline

async def test():
    print('1. Scrapear...')
    csv = await run_scraper_by_keywords(['mouse'], max_results=20)
    
    print('2. Analizar pipeline...')
    stats = await run_pipeline(csv)
    
    print(f'✓ Pipeline completó: {stats[\"pass\"]} viables')

asyncio.run(test())
"
```

- [ ] Full pipeline funciona

---

## 📋 Documentación

- [ ] README.md existe
  ```bash
  ls README.md
  ```

- [ ] SCRAPERS_GUIDE.md existe
  ```bash
  ls SCRAPERS_GUIDE.md
  ```

- [ ] SCRAPER_IMPLEMENTATION_SUMMARY.md existe
  ```bash
  ls SCRAPER_IMPLEMENTATION_SUMMARY.md
  ```

- [ ] examples/README.md existe
  ```bash
  ls examples/README.md
  ```

- [ ] examples/scraper_usage.py existe
  ```bash
  ls examples/scraper_usage.py
  ```

---

## 🎯 Quick Start Verification

### Flujo Mínimo Verificar

1. **Setup OK?**
   ```bash
   docker-compose ps  # Redis y DB deben estar "Up"
   ```

2. **Código importa?**
   ```bash
   python -c "from src.scrapers import ScraperOrchestrator; print('✓')"
   ```

3. **API conecta?**
   ```bash
   python -c "
   import asyncio
   from src.main import run_scraper_by_keywords
   # Si no hay error, está bien
   "
   ```

4. **¿Listo para usar?**
   ```bash
   # Ir a ejemplos:
   python examples/scraper_usage.py
   ```

---

## 🆘 Si algo falla

### Error: "Module not found"
```bash
# Reinstalar paquete en modo desarrollo
pip install -e .
```

### Error: "Redis connection refused"
```bash
# Verificar que Redis corre
docker-compose ps

# Si no, iniciarlo:
docker-compose up -d redis

# O check puerto:
netstat -tulpn | grep 6379
```

### Error: "Keepa API error"
```bash
# Verificar key:
cat .env | grep KEEPA

# Si es vacío, agregar a .env:
KEEPA_API_KEY=tu_api_key_aqui

# Reiniciar
```

### Error: "PostgreSQL connection refused"
```bash
# Verificar que DB corre
docker-compose ps

# Si no, iniciarlo:
docker-compose up -d db

# Esperar 10 segundos y reintentar
```

---

## ✅ Completado!

Cuando hayas marcado todo ☑️ , estás listo para:

```bash
# Opción 1: Ejemplos interactivos
python examples/scraper_usage.py

# Opción 2: Código directo
python -c "
import asyncio
from src.main import run_scraper_by_keywords
asyncio.run(run_scraper_by_keywords(['gaming mouse']))
"
```

---

## 📞 Support

- Leer [SCRAPERS_GUIDE.md](SCRAPERS_GUIDE.md) para uso
- Leer [DEPLOYMENT_AND_TROUBLESHOOTING.md](DEPLOYMENT_AND_TROUBLESHOOTING.md) para problemas
- Leer [API_REFERENCE.md](API_REFERENCE.md) para detalles técnicos

---

**¡Sistema listo para operar! 🚀**
