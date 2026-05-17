# 🧪 Guía: Probar Integración con Base44

## 📋 Descripción
Esta guía te ayudará a verificar que el webhook de Base44 funciona correctamente enviando un **producto fantasma** a través del puente que hemos implementado.

## ✅ Requisitos Previos

1. **Python 3.11+** instalado y en el PATH
2. **Entorno virtual activado**
3. **Dependencias instaladas** (`pip install -e .`)
4. **Base44 webhook URL configurada** en tu archivo `.env`

## 🚀 Pasos para Probar

### Opción 1: Con pytest (Recomendado)

```bash
# 1. Activar entorno virtual
venv\Scripts\activate  # Windows
# o
source venv/bin/activate  # Mac/Linux

# 2. Ejecutar test específico
pytest tests/test_base44_webhook.py -v -s

# 3. Ver output
# ✅ TEST: WEBHOOK DE BASE44
# 📋 Configuración:
#    Base44 URL: https://api.base44.com/...
#    Token configurado: ✓ Sí
# 📦 Producto Fantasma:
#    ASIN: B0PHANTOM01
#    Título: 🎮 Phantom Gaming Mouse Pad RGB - TEST PRODUCT
#    Precio Amazon: €45.99
#    ...
# 🚀 Enviando a Base44...
# ✅ Webhook enviado
```

### Opción 2: Script Directo

```bash
# 1. Activar entorno virtual
venv\Scripts\activate

# 2. Ejecutar script
python test_base44_webhook.py
```

### Opción 3: Desde Python Interactivo

```bash
# 1. Activar entorno virtual
venv\Scripts\activate

# 2. Abrir Python
python

# 3. Ejecutar en consola
>>> import asyncio
>>> from src.pipeline.financial_calc import FinancialResult
>>> from src.pipeline.exporter import send_alert_to_base44

>>> async def test():
...     product = FinancialResult(
...         asin="B0PHANTOM01",
...         ean="0000000000000",
...         title="Test Phantom Product",
...         brand="PhantomBrand",
...         category="Electronics",
...         price_amazon=45.99,
...         buy_price=15.00,
...         bsr_rank=1500,
...         bsr_category="Electronics",
...         bsr_top_pct=0.3,
...         buybox_price=45.99,
...         buybox_seller_name="PhantomSeller",
...         buybox_is_fba=True,
...         fba_fee=8.50,
...         referral_fee=4.60,
...         net_profit=17.89,
...         roi_pct=119.3,
...         scraped_at="2024-05-17T10:30:00",
...         data_source="test_webhook",
...     )
...     await send_alert_to_base44(product)

>>> asyncio.run(test())
```

## 📊 Estructura del Payload Enviado

Cuando el webhook se activa, envía este JSON a Base44:

```json
{
  "asin": "B0PHANTOM01",
  "product_name": "🎮 Phantom Gaming Mouse Pad RGB - TEST PRODUCT",
  "score": 85,
  "amazon_price": 45.99,
  "max_buy_price": 15.00,
  "net_margin": 17.89,
  "roi_percent": 119.3,
  "bsr_percent": 0.3,
  "active_sellers": 5,
  "est_monthly_sales": 300,
  "category": "Electronics",
  "shield_amazon": true,
  "shield_brand": true,
  "shield_massacre": true,
  "shield_account": true
}
```

**Headers:**
```
x-bot-token: <tu_token_si_está_configurado>
Content-Type: application/json
```

## 🔍 Interpretación de Resultados

### ✅ Éxito
```
✅ ÉXITO: Webhook enviado correctamente
   Revisa la URL de Base44 para confirmar la recepción:
   https://api.base44.com/api/apps/TU_APP_ID/functions/webhookAlert
```

**Qué verificar en Base44:**
- Log de eventos recibido
- Datos del producto en el dashboard
- Timestamp correcto

### ⚠️ Configuración Incompleta
```
❌ ERROR: BASE44_WEBHOOK_URL no está configurada en .env
   Por favor, configura BASE44_WEBHOOK_URL en tu archivo .env
```

**Qué hacer:**
1. Abre tu archivo `.env`
2. Reemplaza el placeholder:
   ```
   BASE44_WEBHOOK_URL="https://api.base44.com/api/apps/PON_AQUI_EL_APP_ID/functions/webhookAlert"
   ```
   Por tu URL real:
   ```
   BASE44_WEBHOOK_URL="https://api.base44.com/api/apps/YOUR_REAL_APP_ID/functions/webhookAlert"
   ```

### ⚠️ Token Opcional
Si tienes `BOT_WEBHOOK_TOKEN` configurado, se enviará en los headers. Si no, se enviará sin autenticación:
```
Token configurado: ✗ No  # Esto es OK si Base44 no lo requiere
```

### ❌ Timeout o Error de Conexión
```
⚠️ base44.alert_timeout
   asin=B0PHANTOM01
   url=https://api.base44.com/...
```

**Causas posibles:**
- URL incorrecta
- Base44 está caído
- Red no alcanza el servidor
- Firewall bloqueando la conexión

## 🔗 Flujo Completo del Pipeline

El webhook se dispara automáticamente cuando:

```
1. CSV → Ingestor
2. EAN Resolver → ASIN
3. Shield Chain → Validaciones (5 escudos)
4. Financial Calculator → ROI >= 20% Y BSR <= Top 2%
5. Exporter → Google Sheets + PostgreSQL
6. send_alert_to_base44() → 🔔 WEBHOOK DE BASE44
7. Telegram Bot → Notificación al usuario
```

**El webhook se envía SIEMPRE que hay un FinancialResult aprobado**, sin esperar confirmación.

## 💡 Tips de Debugging

### Habilitar Logs Verbosos
```bash
export LOG_LEVEL=DEBUG  # Mac/Linux
set LOG_LEVEL=DEBUG     # Windows
pytest tests/test_base44_webhook.py -v -s
```

### Ver el JSON que se envía
```python
import json
from src.pipeline.exporter import send_alert_to_base44
from src.pipeline.financial_calc import FinancialResult

# Crear producto
product = FinancialResult(...)

# Mostrar payload
payload = {
    "asin": product.asin,
    "product_name": product.title,
    "score": 85,
    "amazon_price": float(product.buybox_price),
    "max_buy_price": float(product.buy_price),
    "net_margin": float(product.net_profit),
    "roi_percent": float(product.roi_pct),
    "bsr_percent": float(product.bsr_top_pct),
    "active_sellers": 5,
    "est_monthly_sales": 300,
    "category": product.bsr_category,
    "shield_amazon": True,
    "shield_brand": True,
    "shield_massacre": True,
    "shield_account": True,
}

print(json.dumps(payload, indent=2))
```

### Monitorear Logs
```bash
# En Terminal 1
docker-compose logs -f redis postgres

# En Terminal 2
tail -f logs/webhook.log  # Si configuras logs persistentes
```

## 🎯 Próximos Pasos

1. ✅ **Probar webhook** (esta guía)
2. ✅ **Verificar llegada en Base44** (revisar dashboard)
3. 📝 **Configurar alertas en Base44** (crear reglas/notificaciones)
4. 🚀 **Ejecutar pipeline completo** (con datos reales)

## 📞 Soporte

Si el webhook no funciona:

1. Verifica la URL en tu `.env`
2. Verifica conectividad a Base44: `curl https://api.base44.com/`
3. Comprueba headers en el código (`src/pipeline/exporter.py`)
4. Revisa logs con `pytest tests/test_base44_webhook.py -v -s --tb=short`

---

**Última actualización:** 2024-05-17  
**Archivos relacionados:**
- `src/pipeline/exporter.py` - Función `send_alert_to_base44()`
- `tests/test_base44_webhook.py` - Tests de integración
- `test_base44_webhook.py` - Script standalone
