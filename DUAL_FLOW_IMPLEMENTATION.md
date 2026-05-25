# Doble Flujo - Guía de Implementación y Configuración

**Versión:** 2.0  
**Fecha:** Mayo 2026  
**Estado:** ✅ Producción

## 📋 Tabla de Contenidos

1. [Qué es el Doble Flujo](#qué-es-el-doble-flujo)
2. [Arquitectura](#arquitectura)
3. [Instalación](#instalación)
4. [Configuración](#configuración)
5. [Uso](#uso)
6. [Monitoreo](#monitoreo)
7. [Troubleshooting](#troubleshooting)
8. [FAQs](#faqs)

---

## Qué es el Doble Flujo

El **Doble Flujo** (Dual Flow) es un sistema automatizado que ejecuta **dos estrategias de sourcing en paralelo** de forma intercalada:

### 🔄 Flujo 1: Monitor de Tiendas (Sourcing Tradicional)

- **Qué hace:** Realiza scraping de 10 tiendas españolas (Carrefour, El Corte Inglés, FNAC, etc.)
- **Extrae:** EANs y precios de liquidaciones/ofertas
- **Procesa:** Envía datos al pipeline para calcular rentabilidad en Amazon FBA
- **Cuándo:** 2 veces al día (08:00 AM y 20:00 PM por defecto)
- **Duración:** ~30-45 minutos por ejecución
- **Resultados:** Alertas por Telegram con productos viables

### 🤖 Flujo 2: Crawler Autónomo (Reverse Sourcing)

- **Qué hace:** Monitorea Bestsellers, New Releases y Trending de Amazon.es
- **Analiza:** Competencia, velocidad de ventas, margen potencial
- **Cuándo:** Continuamente en los "huecos" del Flujo 1
- **Pausa:** Automáticamente cuando se ejecuta el Flujo 1
- **Reanuda:** Automáticamente después del Flujo 1
- **Resultados:** Alertas automáticas de oportunidades

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                   DualFlowScheduler (Main)                      │
│                    apscheduler + asyncio                        │
└─────────────────────────────────────────────────────────────────┘
         │                                                │
         ▼                                                ▼
    ┌──────────────┐                           ┌────────────────┐
    │  Flujo 1     │                           │   Flujo 2      │
    │  Monitor     │◄─ State Lock ────────────►│   Crawler      │
    │  (CronJob)   │                           │   (Background) │
    └──────────────┘                           └────────────────┘
         │                                            │
         ├─ scrape_all_urls()                        ├─ crawl_bestsellers_loop()
         ├─ write_csv()                              ├─ crawl_new_releases_loop()
         ├─ invoke_pipeline()                        ├─ crawl_trending_loop()
         └─ telegram_notify()                        └─ telegram_notify()

State Machine:
    IDLE ◄───────────────────────────┐
     │                                │
     ├─ [Scheduled] RUNNING_MONITOR   │
     │              │                 │
     │              └─ PAUSED (cooldown) ┐
     │                 │              │
     ├─ [Auto] RUNNING_CRAWLER        │
     │   [Monitors Flow1] ────────────┘
     │
     └─ STOPPING ─► (Graceful Shutdown)
```

### 🔒 Mecanismos de Protección

| Mecanismo | Descripción |
|-----------|-------------|
| **State Lock** | Mutex async para evitar race conditions |
| **Rate Limit Cooldown** | Pausa entre Flujo 1 y Flujo 2 (5 min default) |
| **Max Runtime** | Timeout para Flujo 1 (1 hora default) |
| **Graceful Shutdown** | Signal handling (SIGTERM/SIGINT) |
| **Retry Logic** | Auto-reintento en fallos del Flujo 1 |
| **Telegram Notifications** | Alertas en cada cambio de estado |

---

## Instalación

### 1️⃣ Requisitos Previos

```bash
# Sistema
- Python 3.11+
- PostgreSQL 13+ (o Docker)
- Redis 6+ (o Docker)
- Docker & Docker Compose (recomendado)

# APIs (credenciales)
- SP-API key (Amazon)
- Keepa API key
- Telegram Bot token
```

### 2️⃣ Instalación Manual (Sin Docker)

```bash
# Clonar/acceder al proyecto
cd /path/to/amazon-fba-bot

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o
venv\Scripts\activate  # Windows

# Instalar dependencias (con apscheduler incluido)
pip install -e .

# Verificar instalación
python -c "import apscheduler; print('✓ apscheduler OK')"
```

### 3️⃣ Instalación con Docker (Recomendado)

```bash
# Ir al directorio del proyecto
cd /path/to/amazon-fba-bot

# Construir imagen
docker-compose build

# Iniciar servicios (PostgreSQL + Redis + Scheduler)
docker-compose up -d

# Verificar logs
docker-compose logs -f fba-scheduler
```

---

## Configuración

### 1️⃣ Variables de Entorno (`.env`)

Copia `.env.example` a `.env` y completa:

```bash
cp .env.example .env
```

**Variables principales:**

```env
# APIs
SP_API_REFRESH_TOKEN=Atzr|...
SP_API_CLIENT_ID=amzn1.application-oa2-client...
KEEPA_API_KEY=...
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=987654321

# Base de datos (si no usas Docker)
DATABASE_URL=postgresql+asyncpg://fba:secret@localhost:5432/fba_bot
REDIS_URL=redis://localhost:6379/0

# Doble Flujo (NEW)
DUAL_FLOW_MONITOR_TIMES=08:00 20:00  # Espacios entre horas
DUAL_FLOW_RATE_LIMIT_COOLDOWN=300     # Segundos
DUAL_FLOW_MAX_MONITOR_RUNTIME=60       # Minutos
```

### 2️⃣ Horarios del Flujo 1 (Monitor)

Personaliza en el script de inicio:

```bash
# Default (08:00 y 20:00)
python start_dual_flow.py

# Personalizado (06:00, 12:00, 18:00)
python start_dual_flow.py --monitor "06:00" "12:00" "18:00"

# Con otro cooldown (10 minutos)
python start_dual_flow.py --cooldown 600

# Con timeout diferente (90 minutos)
python start_dual_flow.py --max-runtime 90
```

### 3️⃣ Rate Limit Cooldown

El **cooldown** (pausa entre Flujo 1 y Flujo 2) existe para evitar saturar APIs:

| Servicio | Límites |
|----------|---------|
| **Keepa** | 100 req/min |
| **SP-API** | Depende del plan |
| **Scraping** | Best-effort rate-limiting |

**Recomendaciones:**

- **Desarrollo:** 60 segundos
- **Producción (bajo volumen):** 300 segundos (5 min)
- **Producción (alto volumen):** 600-900 segundos (10-15 min)

```bash
# Producción de alto volumen
python start_dual_flow.py --cooldown 900
```

---

## Uso

### 1️⃣ Inicio Manual

```bash
# Con configuración por defecto
python start_dual_flow.py

# Con logging detallado
python start_dual_flow.py --log-level DEBUG

# Sin Telegram
python start_dual_flow.py --no-telegram
```

### 2️⃣ En Docker

```bash
# Iniciar servicios
docker-compose up -d

# Ver logs en tiempo real
docker-compose logs -f fba-scheduler

# Detener
docker-compose down

# Detener y borrar volúmenes (incluye DB)
docker-compose down -v
```

### 3️⃣ En Servidor (Systemd)

Crear `/etc/systemd/system/fba-bot-dual-flow.service`:

```ini
[Unit]
Description=FBA Bot Doble Flujo (Dual Flow Scheduler)
After=network.target

[Service]
Type=simple
User=fbabot
WorkingDirectory=/opt/amazon-fba-bot
Environment="PATH=/opt/amazon-fba-bot/venv/bin"
EnvironmentFile=/opt/amazon-fba-bot/.env
ExecStart=/opt/amazon-fba-bot/venv/bin/python start_dual_flow.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Activar:

```bash
sudo systemctl enable fba-bot-dual-flow
sudo systemctl start fba-bot-dual-flow
sudo systemctl status fba-bot-dual-flow

# Ver logs
sudo journalctl -u fba-bot-dual-flow -f
```

### 4️⃣ En AWS ECS/Fargate

**Dockerfile** ya incluido. Para ECS:

1. Build & push a ECR:

```bash
aws ecr get-login-password | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com
docker build -t fba-bot:latest .
docker tag fba-bot:latest <account>.dkr.ecr.<region>.amazonaws.com/fba-bot:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/fba-bot:latest
```

2. Crear task definition en ECS con las variables de `.env`
3. Crear service con `Desired count: 1`

---

## Monitoreo

### 📊 Métricas Principales

El scheduler registra automáticamente:

```
scheduler.flow1.started      - Inicio Flujo 1
scheduler.flow1.completed    - Finalización Flujo 1
scheduler.flow1.error        - Error en Flujo 1
scheduler.flow1.timeout      - Timeout en Flujo 1
scheduler.flow2.started      - Inicio Flujo 2
scheduler.flow2.paused       - Pausa Flujo 2 (Flujo 1 activo)
scheduler.flow2.error        - Error en Flujo 2
scheduler.state.changed      - Cambio de estado
```

### 📱 Notificaciones Telegram

Automáticamente recibirás:

```
🚀 Doble Flujo Iniciado
  • Flujo 1 (Monitor): 08:00, 20:00
  • Flujo 2 (Crawler): Automático

⏰ Flujo 1 Iniciado
   Timestamp: 08:00:15

✅ Flujo 1 Completado
   Duración: 2347s
   Ejecución #42

🤖 Flujo 2 Iniciado
   Sesión #123

⏸️  Flujo 2 Pausado
   (Flujo 1 activo)

🛑 Apagando Sistema
   Razón: user_request
   Stats: 42 Monitoreos, 8 Fallos, 123 Sesiones Crawler
```

### 📋 Logs Estructurados

Los logs se guardan con información contextual:

```bash
# Ver en tiempo real
docker-compose logs -f fba-scheduler | grep "flow"

# Filtrar por tipo
docker-compose logs fba-scheduler | grep "flow1.completed"

# Con nivel DEBUG
python start_dual_flow.py --log-level DEBUG
```

---

## Troubleshooting

### ❌ "Cannot connect to PostgreSQL"

**Solución:**

```bash
# Si usas Docker
docker-compose up postgres -d
docker-compose logs postgres  # Ver si está healthy

# Si es local
psql -U fba -d fba_bot -h localhost  # Conectar directamente
```

### ❌ "Telegram: Authentication failed"

**Solución:**

```bash
# Verificar token
grep TELEGRAM_BOT_TOKEN .env

# Test manual
python -c "from src.telegram_bot import TelegramBot; 
           t = TelegramBot('your-token', 'your-chat-id'); 
           import asyncio; 
           asyncio.run(t.send_message('Test'))"
```

### ❌ "Keepa API: Rate limited"

**Solución:**

- Aumentar `--cooldown` (default 300s)
- Reducir concurrencia del pipeline (`PIPELINE_CONCURRENCY`)
- Verificar quota de Keepa API

```bash
python start_dual_flow.py --cooldown 900
```

### ❌ "Flujo 1 siempre timeout"

**Solución:**

- Aumentar `--max-runtime` (está en 60 min por defecto)
- Revisar velocidad de scraping (tiendas pueden estar lentas)
- Revisar logs del monitor:

```bash
python start_dual_flow.py --log-level DEBUG | grep "flow1"
```

### ❌ "Crawler no se reanuda después de Flujo 1"

**Solución:**

- Verificar que el estado no queda en `PAUSED`
- Ver logs:

```bash
docker-compose logs fba-scheduler | grep "state.changed"
```

- Reiniciar:

```bash
docker-compose restart fba-scheduler
```

---

## FAQs

### P: ¿Cuál es el overhead de memoria?

**R:** ~200-400 MB por scheduler + crawler tasks. Con Docker limitado a 1 GB recomendado.

### P: ¿Qué pasa si Flujo 1 no termina antes del próximo horario?

**R:** Se cancela automáticamente (timeout configurable, default 1 hora) y continúa con el siguiente ciclo. Telegram notifica.

### P: ¿Puedo agregar más horarios al Flujo 1?

**R:** Sí, simplemente pasar más `--monitor`:

```bash
python start_dual_flow.py --monitor "08:00" "12:00" "16:00" "20:00"
```

### P: ¿Qué pasa con los datos si se apaga el bot?

**R:** Se pierden los datos no-persistidos en memoria, pero:
- PostgreSQL guarda resultados procesados
- Redis preserva cache (si no se borra)
- Logs quedan en stdout/archivos

### P: ¿Puedo correr múltiples instancias?

**R:** No recomendado. Crearía duplicados. Usar solo una instancia con Docker o systemd.

### P: ¿Cómo monitoreo la salud del sistema?

**R:** 

```bash
# Ver resumen
docker-compose ps

# Health check
curl http://localhost:5000/health  # Si exponemos endpoint

# Logs
docker-compose logs fba-scheduler | tail -50
```

### P: ¿Puedo pausar/reanudar manualmente?

**R:** Actualmente no hay API de control. Crear issue en GitHub si se necesita.

---

## Próximos Pasos

- [ ] Panel web de control (fastapi)
- [ ] Metricas Prometheus/Grafana
- [ ] Alertas en Slack adicional
- [ ] Configuración dinámica (sin reinicio)
- [ ] Simulador de horarios

---

**¿Preguntas?** Consulta los logs o abre un issue. ¡Éxito! 🚀
