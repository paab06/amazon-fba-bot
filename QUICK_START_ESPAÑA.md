# QUICK_START_ESPAÑA.md

## ⚡ Quick Start - Mercado Español (5 minutos)

**Para:** 3 socios que quieren empezar YA

---

## 📝 Checklist Previo (10 minutos)

```
Necesitas tener listos:
☐ Keepa API Key (€20-30/mes)
  → https://keepa.com/#!api
  
☐ Amazon SP-API Keys
  → https://developer.amazon.com/docs/sp-api
  → (Ya deberías tenerlas de antes)
  
☐ Telegram Bot Token
  → @BotFather en Telegram → /newbot
  → Copiar token
  
☐ Docker y Docker Compose instalados
  → Verificar: docker --version
  
☐ PostgreSQL + Redis (o via Docker)
```

---

## 🚀 PASO 1: Configurar .env (2 min)

```bash
# En la raíz del proyecto
cat > .env << 'EOF'
# Marketplace
MARKETPLACE=amazon.es

# APIs
KEEPA_API_KEY=TU_KEY_AQUI
AMAZON_SP_API_KEY=TU_KEY_AQUI
AMAZON_SP_API_SECRET=TU_SECRET_AQUI

# Database
DATABASE_URL=postgresql://fba_bot:password123@postgres:5432/fba_bot
REDIS_URL=redis://redis:6379

# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCDEFGHijklmnopqrstuvwxyzABCDEFG
TELEGRAM_CHAT_ID=TU_CHAT_ID_AQUI

# Crawler
CRAWLER_ENABLED=true
CRAWLER_DURATION_HOURS=0
CRAWLER_SEND_ALERTS=true
EOF

# Editar valores con tus keys
nano .env
```

---

## 🐳 PASO 2: Levantar Servicios (1 min)

```bash
# Levantar postgres, redis, bot
docker-compose up -d

# Verificar que están UP
docker-compose ps
```

**Debe mostrar:**
```
NAME                STATUS
postgres            Up
redis               Up
```

---

## ▶️ PASO 3: Ejecutar el Bot (Indefinido)

```python
# Crear archivo: run_bot_spain.py

import asyncio
from src.main import run_autonomous_mode

async def main():
    print("🚀 Iniciando bot autónomo para Amazon.es...")
    await run_autonomous_mode(
        duration_hours=0,  # Indefinido (24/7)
        send_telegram_alerts=True
    )

if __name__ == "__main__":
    asyncio.run(main())
```

```bash
# Ejecutar
python run_bot_spain.py

# O en background (Linux/Mac)
nohup python run_bot_spain.py > bot.log 2>&1 &

# Ver logs en tiempo real
tail -f bot.log
```

---

## 📱 PASO 4: Ver Alertas en Telegram

Después de 4-6 horas, recibirás mensajes como:

```
🎯 VIABLE ENCONTRADO

📦 PICTEK Gaming Mouse Pad
   ASIN: B07XYZ123
   Precio: €45.99
   Margen: €27.49

████████░░ 82/100
✅ EXCELENTE - Compra inmediatamente
```

---

## 📊 PASO 5: Decisión Rápida (< 2 minutos)

**Para cada alerta:**

```
Preguntas:
1. ¿Score >= 75? → SÍ = Comprar
2. ¿Score 50-75? → Revisar datos
3. ¿Score < 50? → NO comprar

Acción:
✓ Compra: Enviar link al socio de logística
⚠️ Revisar: Analizar más a fondo
✗ Paso: Ignorar
```

---

## 🔍 Interpretar el Score

```
█████████████████████ 90/100 = EXCELENTE ✅
████████████████░░░░░ 80/100 = EXCELENTE ✅
████████████░░░░░░░░░ 70/100 = BUENO ✓
████████░░░░░░░░░░░░░ 60/100 = REVISAR ⚠️
█████░░░░░░░░░░░░░░░░ 45/100 = RECHAZA ❌
```

**Regla simple:**
- 75+: Compra inmediato
- 50-75: Revisar manualmente
- <50: No compres

---

## ⚙️ Configurar España Específicamente

```python
# En: src/scrapers/autonomous_crawler.py

# YA CONFIGURADO PARA ESPAÑA:
ESPAÑA_CATEGORIES = [
    "Electronics",       # Gaming mice, headsets
    "Home & Garden",     # Organizadores, almacenamiento
    "Sports & Outdoors", # Fitness, outdoor gear
    "Gaming",            # Gaming peripherals
]

ESPAÑA_BESTSELLER_FILTERS = {
    "max_bsr": 50000,           # Top 5%
    "price_range": (15, 200),   # €15-200 (margen bueno)
    "min_reviews": 30,          # Mínimo 30 reviews
}

ESPAÑA_CRAWLER_PARAMS = {
    "bestseller_interval_hours": 4,  # Cada 4 horas
    "new_releases_interval_hours": 2, # Cada 2 horas
    "trending_interval_hours": 6,    # Cada 6 horas
}
```

**No necesitas tocar nada - ya está configurado.**

---

## 📈 Esperar Resultados

### Primeras 2 horas
```
✓ Bot iniciado
✓ Conectando a Keepa API
✓ Descargando bestsellers
✓ Analizando primeros 100+ productos
```

### Primeras 4 horas
```
✓ Primer lote de viables encontrado
✓ Competitive analysis completo
✓ PRIMERAS ALERTAS EN TELEGRAM
```

### Primeras 24 horas
```
✓ 20-30 nuevos viables identificados
✓ Score breakdown en Telegram
✓ Lista lista para decisiones
```

---

## 🛡️ Problemas Comunes

### "No recibo alertas en Telegram"

```bash
# 1. Verificar logs
tail bot.log | grep telegram

# 2. Si error "Chat ID inválido"
# → Ir a Telegram
# → @BotFather → /mybots → Tu bot → Edit commands
# → Copiar token exactamente en .env

# 3. Reiniciar
Ctrl+C en terminal
python run_bot_spain.py
```

### "Bot se para después de 1 hora"

```bash
# Probablemente error en Keepa o SP-API
tail -200 bot.log

# Buscar "error" o "exception"
# Si es Keepa: Verificar API key válida
# Si es SP-API: Verificar credentials válidos
```

### "Muy pocas alertas (< 5/día)"

Posibles causas:
1. Parámetros muy restrictivos
   → Bajar `min_reviews` a 20
   → Subir `max_bsr` a 100000

2. Categorías sin productos
   → Verificar selección de categorías

3. Crawler no está buscando
   → Ver logs si está en las loops

---

## 📞 Para 3 Socios

### Socio 1: "Estrategia"
```
Tu rol: Decidir compras

8:00 AM: Revisar Telegram alertas
         Decidir: ✅ Compra / ⚠️ Revisar / ❌ Paso
         Enviar decisión a Socio 3

Tiempo: 10-15 minutos
```

### Socio 2: "Técnico"
```
Tu rol: Mantener bot corriendo

9:00 AM: docker-compose ps
         docker-compose logs bot --tail=50
         Verificar: ✓ UP, ✓ No errors

Tiempo: 2 minutos
```

### Socio 3: "Operaciones"
```
Tu rol: Ejecutar compras

9:30 AM: Recibir lista de Socio 1
         Buscar en proveedores
         Confirmar precio
         Encargo

Tiempo: 5 minutos × N productos
```

---

## 🎯 Meta Mes 1

```
Semana 1: "Setup y observación"
  • Bot corriendo sin errores
  • Recibiendo alertas en Telegram
  • Entender qué es "viables"

Semana 2-3: "Primeras compras"
  • 3-5 productos comprados
  • Aprender proveedores
  • ROI empieza a verse

Semana 4: "Escalado inicial"
  • 10-15 compras total
  • Ganancia real (>€200)
  • Parámetros optimizados
```

---

## 📱 Crear Grupo Telegram (Recomendado)

```
1. Crear grupo en Telegram
2. Socio 1, 2, 3 adentro
3. Bot enviando alertas al grupo
4. Daily standup en grupo (5 min)

Grupo chat:
09:15 S1: "5 nuevos viables, scores: 82, 78, 65, 71, 80"
09:16 S2: "Bot OK, 200 productos analizados esta noche"
09:17 S3: "Listo para encargos, cuales compramos?"
```

---

## 🚨 IMPORTANTE

```
⚠️ Revisar siempre datos antes de comprar
- No confíes 100% en score
- Verificar precio en proveedor
- Confirmar stock disponible
- Revisar tiempo de envío
- Chequear reviews del proveedor
```

---

## ✅ Verificación Final

Antes de terminar:

```bash
# 1. Bot corriendo?
ps aux | grep run_bot_spain.py
# Debe estar en la lista

# 2. Docker services UP?
docker-compose ps
# postgres UP, redis UP

# 3. Telegram bot token funciona?
# (Ya debería funcionar si llegaste aquí)

# 4. Keepa API key válido?
# (Verificaré en primeros logs)
```

---

## 🚀 LISTO - YA PUEDES EMPEZAR

El sistema está **totalmente configurado para Amazon.es** 🇪🇸

Ahora:
1. Ejecuta `python run_bot_spain.py`
2. Espera 4-6 horas primeras alertas
3. Reúnete con los 3 socios
4. Toma decisiones
5. **¡A ganar!**

---

**Cualquier problema: Revisar logs o consultar AUTONOMOUS_MODE_GUIDE.md**

¡Éxito! 🚀
