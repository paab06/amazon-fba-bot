# 🌉 Diagrama: Puente Base44 Implementado

## Arquitectura del Flujo

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PIPELINE COMPLETO                           │
└─────────────────────────────────────────────────────────────────────┘

    CSV
     │
     ├──→ [1️⃣ INGESTOR]
     │        │ Validar datos
     │        └──→ ScrapedProduct
     │
     ├──→ [2️⃣ EAN RESOLVER]
     │        │ EAN → ASIN (SP-API)
     │        └──→ ResolvedProduct
     │
     ├──→ [3️⃣ SHIELD CHAIN]
     │        │ 5 validaciones de seguridad
     │        │ ├─ Blacklist
     │        │ ├─ Amazon en BuyBox
     │        │ ├─ Brand check
     │        │ ├─ Massacre detector
     │        │ └─ Gating check
     │        └──→ EnrichedProduct (PASS)
     │
     ├──→ [4️⃣ FINANCIAL CALC]
     │        │ ROI >= 20% ✓
     │        │ BSR <= Top 2% ✓
     │        └──→ FinancialResult (VIABLE)
     │
     ├──→ [5️⃣ EXPORTER]
     │        │
     │        ├──→ Google Sheets ✓
     │        │
     │        ├──→ PostgreSQL ✓
     │        │
     │        └──→ [🌉 BASE44 WEBHOOK] ← AQUÍ ESTAMOS AHORA
     │             │
     │             └──→ POST a Base44
     │                  ├─ URL: settings.base44_webhook_url
     │                  ├─ Body: JSON con datos del producto
     │                  ├─ Header: x-bot-token (si está configurado)
     │                  └─ Respuesta: 200 OK ✓
     │
     └──→ [6️⃣ TELEGRAM BOT]
              │ Notificar usuario
              └──→ 📱 Mensaje al chat
```

## 🌉 Detalles del Puente Base44

### Ubicación en el Código

```python
# src/pipeline/exporter.py

async def send_alert_to_base44(result: FinancialResult) -> None:
    """
    Envía una alerta a Base44 con los datos del producto aprobado.
    Se dispara DESPUÉS de guardar en Google Sheets y PostgreSQL.
    """
    
    # 1. Verificar que URL está configurada
    if not settings.base44_webhook_url:
        log.debug("base44.webhook_skipped", reason="webhook_url_not_configured")
        return
    
    # 2. Preparar payload
    payload = {
        "asin": result.asin,
        "product_name": result.title,
        "score": 85,
        "amazon_price": float(result.buybox_price),
        "max_buy_price": float(result.buy_price),
        "net_margin": float(result.net_profit),
        "roi_percent": float(result.roi_pct),
        "bsr_percent": float(result.bsr_top_pct),
        "active_sellers": 5,
        "est_monthly_sales": 300,
        "category": result.bsr_category,
        "shield_amazon": True,
        "shield_brand": True,
        "shield_massacre": True,
        "shield_account": True,
    }
    
    # 3. Preparar headers
    headers = {}
    if settings.bot_webhook_token:
        headers["x-bot-token"] = settings.bot_webhook_token
    
    # 4. Enviar HTTP POST
    async with aiohttp.ClientSession() as session:
        async with session.post(
            settings.base44_webhook_url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            # 5. Log resultado
            if response.status == 200:
                log.info("base44.alert_sent", asin=result.asin)
            else:
                log.warning("base44.alert_failed", status=response.status)
```

### Configuración en .env

```env
# Base44 Webhook
BASE44_WEBHOOK_URL="https://api.base44.com/api/apps/TU_APP_ID/functions/webhookAlert"

# Opcional: Token de autenticación
BOT_WEBHOOK_TOKEN="tu_token_aqui"  # Opcional
```

### Configuración en config.py

```python
# src/core/config.py

class Settings(BaseSettings):
    ...
    
    # ── Base44 Webhook ────────────────────────────────────────────
    base44_webhook_url: str | None = Field(
        None, 
        description="URL del webhook de Base44"
    )
    bot_webhook_token: str | None = Field(
        None, 
        description="Token de autenticación para el webhook"
    )
    
    ...
```

## 📊 Flujo de Datos del Payload

```
FinancialResult (objeto Python)
│
├─ asin: "B07XYZ123"
├─ title: "Gaming Mouse Pad RGB"
├─ buybox_price: 45.99 (€)
├─ buy_price: 15.00 (€)
├─ net_profit: 17.89 (€)
├─ roi_pct: 119.3 (%)
├─ bsr_top_pct: 0.3 (%)
├─ bsr_category: "Electronics"
└─ ... otros campos
│
                ↓
        Convertir a JSON
│
{
  "asin": "B07XYZ123",
  "product_name": "Gaming Mouse Pad RGB",
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
│
                ↓
        HTTP POST
│
POST /api/apps/TU_APP_ID/functions/webhookAlert HTTP/1.1
Host: api.base44.com
Content-Type: application/json
x-bot-token: tu_token_aqui
Content-Length: 432

[JSON PAYLOAD]
│
                ↓
        Base44 recibe y procesa
│
✓ 200 OK → log.info("base44.alert_sent")
✗ Error  → log.warning("base44.alert_failed")
```

## 🔄 Ciclo de Vida de un Producto

```
Producto fantasma B0PHANTOM01 entra al pipeline:

1. INGESTOR
   Input:  ASIN: B0PHANTOM01, Precio: €45.99
   Output: ScrapedProduct
   Status: ✓ Validado

2. EAN RESOLVER
   Input:  ScrapedProduct
   Output: ResolvedProduct
   Status: ✓ EAN resuelto

3. SHIELD CHAIN (5 escudos)
   Input:  ResolvedProduct
   Check:  Blacklist ✓
   Check:  Amazon BB ✓
   Check:  Brand ✓
   Check:  Massacre ✓
   Check:  Gating ✓
   Output: EnrichedProduct
   Status: ✓ Todas las validaciones pasadas

4. FINANCIAL CALC
   Input:  EnrichedProduct
   ROI:    119.3% >= 20% ✓
   BSR:    0.3% <= 2% ✓
   Output: FinancialResult
   Status: ✓ Viable para exportar

5. EXPORTER
   Output 1: Google Sheets   ✓ Fila agregada
   Output 2: PostgreSQL      ✓ Guardado en DB
   Output 3: Base44          ← [WEBHOOK]
             │
             ├─ Verifica URL configurada
             ├─ Prepara JSON payload
             ├─ POST a https://api.base44.com/...
             ├─ Headers: x-bot-token (si existe)
             └─ Espera respuesta 200 OK
   
   Status: ✓ Webhook enviado

6. TELEGRAM BOT
   Input:  Producto viable notificado
   Output: 📱 Mensaje al usuario
   Status: ✓ Notificación enviada
```

## ✨ Características del Puente

| Aspecto | Detalle |
|---------|---------|
| **Tipo** | HTTP POST (asincrónico) |
| **Autenticación** | Header opcional `x-bot-token` |
| **Payload** | JSON con 16 campos de datos |
| **Timeout** | 10 segundos |
| **Error Handling** | Fail-safe (no bloquea pipeline) |
| **Logging** | Estructurado con structlog |
| **Configuración** | Via `.env` (BASE44_WEBHOOK_URL) |
| **Sincronización** | Se dispara DESPUÉS de guardar en BD |

## 🧪 Prueba de Producto Fantasma

```
Producto de prueba: B0PHANTOM01
├─ Título: 🎮 Phantom Gaming Mouse Pad RGB - TEST PRODUCT
├─ Marca: PhantomBrand
├─ Precio Amazon: €45.99
├─ Precio de Compra: €15.00
├─ Margen Neto: €17.89
├─ ROI: 119.3% ✓ (viable)
├─ BSR: 0.3% ✓ (top)
├─ Todos los Escudos: ✓ PASS
└─ Base44: ✓ Webhook enviado

Respuesta esperada:
HTTP/1.1 200 OK
{
  "status": "received",
  "product_id": "B0PHANTOM01",
  "timestamp": "2024-05-17T10:30:00Z"
}
```

## 🎯 Ventajas del Diseño

1. **Asincrónico** - No bloquea el pipeline aunque Base44 sea lento
2. **Configurable** - Se habilita/deshabilita via `.env`
3. **Resiliente** - Si falla, continúa el pipeline
4. **Auditable** - Logs estructurados de cada intento
5. **Flexible** - Soporta autenticación por token
6. **Documentado** - Payload claro y bien definido

---

**Ver también:**
- [BASE44_TESTING_GUIDE.md](BASE44_TESTING_GUIDE.md) - Guía de pruebas
- [src/pipeline/exporter.py](src/pipeline/exporter.py) - Código fuente
- [tests/test_base44_webhook.py](tests/test_base44_webhook.py) - Tests automatizados
