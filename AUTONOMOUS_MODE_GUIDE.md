# AUTONOMOUS_MODE_GUIDE.md

## 🚀 Guía Definitiva del Sistema Autónomo

**Para: 3 Socios - Amazon.es - Empezando**

---

## 📋 Tabla de Contenidos

1. [Overview](#overview)
2. [Cómo Funciona](#cómo-funciona)
3. [Para Cada Socio](#para-cada-socio)
4. [Setup y Configuración](#setup-y-configuración)
5. [Usar el Sistema](#usar-el-sistema)
6. [Interpretar Resultados](#interpretar-resultados)
7. [Troubleshooting](#troubleshooting)

---

## 🎯 Overview

### Antes (Manual)
```
Socio 1: Busca "mouse" en Amazon.es → 2 horas
         Encuentra 10 candidatos
         ↓
Socio 2: Analyzes ROI → 1 hora
         Encuentra 2 viables
         ↓
Socio 3: Compra
```

### Ahora (Automático)
```
Bot 24/7:
Busca bestsellers → Analiza viabilidad → Filtra competencia
     ↓
Telegram: "🎯 VIABLE: Gaming Mouse Pad - €30 margen - Score 82/100"
     ↓
Socio: Lee en 2 minutos, decide comprar o no
```

---

## 🔄 Cómo Funciona

### Paso 1: CRAWLER (Búsqueda Automática)
```
Cada 2-6 horas busca en Amazon.es:
├─ Bestsellers (cada 4h)
├─ New releases (cada 2h)
└─ Trending products (cada 6h)

De cada categoría: 500+ productos
Aplicar filtros:
├─ Precio: €15-200
├─ BSR: Top 5%
├─ Reviews: 30+ (legítimo)
└─ Resultado: 100-200 candidatos/día
```

### Paso 2: PIPELINE EXISTING (Validación)
```
Para CADA candidato:
├─ Escudo 1: ¿Marca en blacklist?
├─ Escudo 2: ¿Amazon en Buy Box?
├─ Escudo 3: ¿Masacre FBA detectada?
├─ Escudo 4: ¿Gating/restricción?
├─ Búsqueda: Precio mínimo en proveedores
└─ ROI: Calcular margen

Resultado: ¿Margen >= €15? ¿ROI >= 100%?
```

### Paso 3: COMPETITIVE ANALYZER (Análisis Profundo)
```
Para los que pasaron pipeline, adicional análisis:
├─ FBA Competition (25%): ¿Cuántos vendedores?
├─ Price Trend (25%): ¿Precio sube o baja?
├─ Sales Velocity (25%): ¿Vende rápido o lento?
├─ Category Saturation (15%): ¿Nicho o saturado?
└─ Price Advantage (10%): ¿Tienes ventaja?

Score 0-100 basado en ponderación
```

### Paso 4: TELEGRAM ALERTS (Acción)
```
Si Score >= 75: ✅ EXCELENTE
  "Compra inmediatamente"
  
Si Score 50-75: ⚠️ BORDERLINE
  "Revisar manualmente antes"
  
Si Score < 50: ❌ RECHAZA
  "No comprar, riesgo alto"
```

---

## 👥 Para Cada Socio

### SOCIO 1: "El Estratega" (Jefe de Operaciones)

**Tu Rol:**
- Configurar categorías y parámetros
- Revisar alertas a primera hora
- Decidir qué productos comprar

**Acciones Diarias:**
```
8:00 AM: Revisar Telegram
         "5 nuevos viables encontrados"
         Score breakdown para cada uno
         ↓
         Decidir: ¿Compro? ¿Espero? ¿Paso?

         
2-3 minutos por producto
Total: 10-15 minutos/día
```

**Configuración Responsable:**
```python
CATEGORIA_CONFIG = {
    "Electronics": {
        "min_margin": 15,
        "min_roi": 100,
        "max_competitors": 20
    },
    "Home & Garden": {
        "min_margin": 12,
        "min_roi": 100,
        "max_competitors": 15
    }
}
```

---

### SOCIO 2: "El Técnico" (Operations)

**Tu Rol:**
- Mantener servidor corriendo
- Monitorear logs
- Solucionar problemas
- Actualizar parámetros del crawler

**Acciones Diarias:**
```
9:00 AM: Verificar bot está corriendo
         docker-compose ps
         
         Ver logs
         docker-compose logs bot --tail=50
         
         Totales del crawler
         "Checked: 500 products"
         "Passed filters: 120 candidates"
         "Pipeline viable: 15"
         "Telegram alerts: 5"

1-2 minutos
```

**Comandos Básicos:**
```bash
# Ver estado
docker-compose ps

# Ver logs en vivo
docker-compose logs -f bot

# Reiniciar
docker-compose restart bot

# Estadísticas
docker-compose logs bot | grep "viable_found"
```

---

### SOCIO 3: "El Logístico" (Fulfillment)

**Tu Rol:**
- Ejecutar compras aprobadas
- Preparar envíos a FBA
- Monitorear stock

**Acciones Diarias:**
```
9:30 AM: Recibir lista de ASINs aprobados
         Socio 1: "Compra estos 3 productos"
         ↓
         Para cada ASIN:
         1. Ir a provedor (AliExpress/Alibaba)
         2. Copiar link
         3. Checkear stock
         4. Confirmar precio
         5. Encargar

3-5 minutos por ASIN
Total: 15-25 minutos/día
```

**Checklist por Compra:**
```
☐ ASIN confirmado
☐ Stock disponible en proveedor
☐ Precio <= costo calculado
☐ Envío incluído?
☐ Tiempo de envío aceptable?
☐ Comprador (puedo recibir)?
☐ Pedir
```

---

## 🔧 Setup y Configuración

### Requisitos

```
✓ Servidor propio (homelab)
✓ Docker + Docker Compose
✓ Keepa API Key (€20-30/mes)
✓ SP-API Key (Amazon)
✓ Telegram Bot Token (gratis)
✓ PostgreSQL (local)
✓ Redis (local)
```

### 1️⃣ Configurar .env

```bash
# .env
MARKETPLACE=amazon.es

# APIs
KEEPA_API_KEY=tu_key_aqui
AMAZON_SP_API_KEY=tu_key_aqui
AMAZON_SP_API_SECRET=tu_secret_aqui

# Database
DATABASE_URL=postgresql://user:pass@localhost/fba_bot
REDIS_URL=redis://localhost:6379

# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCDEFGHijklmnopqrstuvwxyzABCDEFG
TELEGRAM_CHAT_ID=987654321

# Crawler
CRAWLER_ENABLED=true
CRAWLER_DURATION_HOURS=0  # 0 = indefinido
CRAWLER_SEND_ALERTS=true
```

### 2️⃣ Iniciar Servicios

```bash
# Levantar database + redis + bot
docker-compose up -d

# Verificar
docker-compose ps
# Debe mostrar: postgres, redis, bot → Up
```

### 3️⃣ Configurar Parámetros

```python
# src/scrapers/autonomous_crawler.py

ESPAÑA_CATEGORIES = [
    "Electronics",      # ✓ Recomendado
    "Home & Garden",    # ✓ Recomendado
    "Sports & Outdoors",# ✓ Recomendado
    "Gaming",           # ✓ Recomendado
]

# NO incluir:
# - "Toys & Games" (muy estacional)
# - "Books" (0 margen)
# - "Clothing" (muy saturado)
```

---

## 🚀 Usar el Sistema

### Opción A: Correr Indefinido (RECOMENDADO)

```python
# Archivo: run_bot.py
import asyncio
from src.main import run_autonomous_mode

async def main():
    await run_autonomous_mode(
        duration_hours=0,  # Indefinido
        send_telegram_alerts=True
    )

if __name__ == "__main__":
    asyncio.run(main())
```

```bash
# Ejecutar (en background)
nohup python run_bot.py > bot.log 2>&1 &

# O en systemd (mejor)
# Crear /etc/systemd/system/fba-bot.service
```

### Opción B: Correr por Tiempo Limitado (TESTING)

```python
# Correr por 24 horas
await run_autonomous_mode(
    duration_hours=24,
    send_telegram_alerts=True
)
```

### Opción C: Scheduler (Muy Recomendado)

```python
# src/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.main import run_autonomous_mode

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('cron', hour=9, minute=0)
async def crawl_morning():
    """Correr crawler de 9 AM a 5 PM"""
    await run_autonomous_mode(duration_hours=8)

@scheduler.scheduled_job('cron', hour=21, minute=0)
async def crawl_evening():
    """Correr crawler de 9 PM a 5 AM"""
    await run_autonomous_mode(duration_hours=8)

scheduler.start()
```

---

## 📊 Interpretar Resultados

### Alert en Telegram

```
🎯 VIABLE ENCONTRADO (BESTSELLERS)

📦 Producto:
  ASIN: B07XYZ123
  Título: Gaming Mouse Pad RGB 800x300mm
  Marca: PICTEK

💰 ANÁLISIS FINANCIERO:
  Precio Amazon: €45.99
  Costo Mínimo: €18.50
  Margen: €27.49
  ROI: 148%

📊 MÉTRICAS:
  BSR: 1,250 (Top 1% en categoría)
  Reviews: 2,500
  Rating: 4.6/5

🏆 ANÁLISIS DE COMPETENCIA:
████░░░░░░ 82/100

DESGLOSE:
├─ FBA Competencia: ████████░ 20/25 (6 sellers)
├─ Trend Precios: ███████░░ 18/25 (Estable)
├─ Velocidad Venta: ████████░ 24/25 (15 units/día)
├─ Saturación: ██████░░░ 10/15 (Nicho moderado)
└─ Ventaja Precio: ████████░░ 8/10

✅ EXCELENTE

• Competencia baja (solo 6 vendedores FBA)
• Precio muy estable
• Venta muy rápida (dinero rápido)

Link: https://amazon.es/dp/B07XYZ123
```

### Interpretar Scores

```
SCORE >= 75: ✅ EXCELENTE
  → Compra inmediatamente
  → Riesgo bajo
  
SCORE 50-75: ⚠️ BORDERLINE
  → Revisar manualmente
  → Posible si confías en tu análisis
  
SCORE < 50: ❌ RECHAZA
  → Riesgo alto
  → NO comprar
```

### Métricas Importantes

```
FBA Competencia:
  1-3 sellers = ✅ Excelente (nicho)
  4-10 = 🟡 Bueno
  10-20 = 🟡 Aceptable
  20+ = ❌ Saturado

Price Trend:
  Subiendo = ✅ Oportunidad
  Estable = ✅ Bueno
  Bajando poco = 🟡 Cuidado
  Bajando mucho = ❌ Evita

Sales Velocity:
  10+ units/día = ✅ Rápido (dinero rápido)
  5-10 = ✅ Normal
  2-5 = 🟡 Lento
  <2 = ❌ Muy lento
```

---

## 🐛 Troubleshooting

### "Bot no está enviando alertas"

```bash
# 1. Verificar que está corriendo
docker-compose ps
# Bot debe estar "Up"

# 2. Ver logs
docker-compose logs bot --tail=100

# 3. Verificar Telegram key
grep TELEGRAM .env

# 4. Test manual de Telegram
python -c "
import asyncio
from src.core.config import settings
# Debería imprimir token

# 5. Reiniciar
docker-compose restart bot
```

### "Crawler no encuentra productos"

```bash
# Verificar Keepa key
grep KEEPA .env

# Test de Keepa API
python -c "
import asyncio
from src.api.keepa_client import KeepaClient
client = KeepaClient()
# Test get_bestsellers
"

# Si error: Key inválida o expirada
```

### "ROI muy bajo o margen imposible"

```
Posibles causas:
1. Parámetros muy agresivos
   → Ajustar min_margin más bajo
   
2. Categoría saturada
   → Cambiar a categoría diferente
   
3. Proveedores caros
   → Buscar proveedores alternativos
```

### "PostgreSQL/Redis no inician"

```bash
# Ver qué puerto está ocupado
lsof -i :5432  # PostgreSQL
lsof -i :6379  # Redis

# Kill proceso conflictivo
kill -9 <PID>

# Intentar nuevamente
docker-compose up -d
```

---

## 💡 Tips para Maximizar

### 1. Sincronización de Socios

```
Recomendación: Reunión breve DIARIA (5 min)

9:15 AM:
Socio 1: "5 nuevos viables, scores 78, 82, 65, 71, 80"
Socio 2: "Bot funcionando OK, 250 productos analizados"
Socio 3: "Última compra llegó, lista para enviar a FBA"

Decisiones rápidas:
"Comprar los 4 de score >70"
"Esperar en el de 65"
```

### 2. Optimizar Categorías

```
MES 1: Prueba todas las categorías
Medir: ¿Cuál tiene más viables?
       ¿Cuál tiene mejor margen?
       ¿Cuál tiene mejor score competitivo?

Resultado: Top 2 categorías
MES 2: Focus en esas 2 solamente
```

### 3. Escalar Volumen

```
FASE 1 (Ahora):
- 3-5 compras/semana
- 1 categoría
- Presupuesto: €500-1000

FASE 2 (Mes 2-3):
- 10-15 compras/semana
- 2-3 categorías
- Presupuesto: €2000-5000

FASE 3 (Mes 3+):
- 30+ compras/semana
- Todas categorías
- Presupuesto: €10,000+
```

---

## 📞 Contacto y Soporte

- **Setup Issues:** Revisar CHECKLIST_SETUP.md
- **API Issues:** Revisar API_REFERENCE.md
- **Business Logic:** Revisar SCRAPERS_GUIDE.md
- **Code:** Revisar SCRAPER_IMPLEMENTATION_SUMMARY.md

---

## 🎯 Meta para Mes 1

```
OBJETIVO:
- 20-30 productos viables identificados
- 10-15 comprados
- ROI mínimo: 80% (real, no teórico)
- Aprender el mercado

MÉTRICAS DE ÉXITO:
✓ Bot corriendo 24/7 sin errores
✓ Alerts llegando a Telegram
✓ Decisiones rápidas (< 5 min/alert)
✓ Primeras ganancias en 2-3 semanas
```

---

**¡A escalar! 🚀**

Cualquier pregunta: Revisar docs o hacer PR con mejoras.
