# Quick Start - Doble Flujo Automatizado

⏱️ **Tiempo estimado de setup: 5 minutos**

## 🚀 Opción 1: Docker (Recomendado)

```bash
# 1. Navega al proyecto
cd /ruta/a/amazon-fba-bot

# 2. Configura variables de entorno
cp .env.example .env
# Edita .env con tus credenciales (SP-API, Keepa, Telegram, etc.)
nano .env  # o usa tu editor favorito

# 3. Construye e inicia
docker-compose up -d

# 4. Verifica que está corriendo
docker-compose logs -f fba-scheduler

# Deberías ver:
# ✅ scheduler.initialized
# ✅ scheduler.started
# ✅ scheduler.flows.ready
```

## 🚀 Opción 2: Ejecutar Localmente

```bash
# 1. Prerequisites
python --version  # Verificar Python 3.11+
# Asegurar que PostgreSQL y Redis están corriendo

# 2. Setup
cd /ruta/a/amazon-fba-bot
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# 3. Instalar
pip install -e .

# 4. Configurar .env
cp .env.example .env
# Edita con tus credenciales

# 5. Correr
python start_dual_flow.py
```

## ⚙️ Configuración Básica

### Horarios del Flujo 1

```bash
# Default: 08:00 y 20:00
python start_dual_flow.py

# Custom: 06:00, 12:00, 18:00
python start_dual_flow.py --monitor "06:00" "12:00" "18:00"

# Para Docker: edita docker-compose.yml, comando del servicio fba-scheduler
```

### Rate Limit Cooldown

```bash
# Default: 300 segundos (5 minutos)
python start_dual_flow.py

# Aumentar para APIs lentas: 900 segundos (15 minutos)
python start_dual_flow.py --cooldown 900
```

## 📊 Monitorear

```bash
# En Docker
docker-compose logs -f fba-scheduler

# En local
# Mira la salida del terminal

# En Telegram
# Recibirás notificaciones automáticas de cada flujo
```

## ⏹️ Detener

```bash
# Docker
docker-compose down

# Local
# Presiona Ctrl+C
# O envía SIGTERM
```

## 🔍 Verificar que está funcionando

### Checklist

- [ ] Servicio iniciado sin errores
- [ ] PostgreSQL y Redis conectados
- [ ] Notificación Telegram inicial recibida
- [ ] Logs muestran `scheduler.flows.ready`
- [ ] Próxima ejecución Flujo 1 listada en logs

### Esperar confirmación

- **A la próxima hora programada (ej. 08:00):**
  - Verás `scheduler.flow1.started`
  - Telegram: "⏰ Flujo 1 Iniciado"
  - Scraping de tiendas en progreso

- **Después de terminar Flujo 1:**
  - Verás `scheduler.flow1.completed`
  - Pausa de rate limit (5 min default)
  - Flujo 2 se reanuda

---

## 🐛 Troubleshooting Rápido

| Problema | Solución |
|----------|----------|
| "Cannot connect to postgres" | `docker-compose up postgres -d` |
| "Telegram authentication failed" | Verificar TELEGRAM_BOT_TOKEN en .env |
| "No Flujo 1 started" | Revisar hora del sistema, horarios en config |
| "Fljo 2 never resumes" | Ver logs con DEBUG: `--log-level DEBUG` |
| "API rate limited" | Aumentar cooldown: `--cooldown 900` |

---

## 📚 Documentación Completa

Ver **DUAL_FLOW_IMPLEMENTATION.md** para:
- Arquitectura detallada
- Variables de entorno
- Deployment en servers
- Monitoreo avanzado
- FAQs

---

¡Ya está! El sistema está corriendo 24/7 intercalando ambos flujos. 🎉

**¿Preguntas?** Consulta los logs o abre un issue.
