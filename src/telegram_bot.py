"""
Telegram Bot para alertas de productos viables

Envía alertas con:
- Producto encontrado
- Score competitivo (0-100)
- Margen y ROI
- Botones: Compra / Revisar / Paso
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional, Callable

import aiohttp
import structlog

from src.core.config import settings

log = structlog.get_logger(__name__)


@dataclass
class TelegramAlert:
    """Alert que enviar a Telegram"""
    asin: str
    title: str
    price: float
    cost: float
    margin: float
    roi: float
    score: int
    recommendation: str
    fba_competitors: int
    category: str


class TelegramBot:
    """
    Bot de Telegram para alertas automáticas
    
    Uso:
        bot = TelegramBot(token, chat_id)
        await bot.send_alert(alert_data)
    """
    
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.session: Optional[aiohttp.ClientSession] = None
        self._callbacks: dict[str, Callable] = {}
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    async def _ensure_session(self):
        """Crear sesión si no existe"""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Enviar mensaje simple"""
        try:
            await self._ensure_session()
            
            async with self.session.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    log.info("telegram.message_sent")
                    return True
                else:
                    log.error("telegram.send_failed", status=resp.status)
                    return False
        except Exception as e:
            log.error("telegram.error", error=str(e))
            return False
    
    async def send_alert(self, alert: TelegramAlert) -> bool:
        """
        Enviar alerta de producto viable
        
        Formato:
        🎯 VIABLE ENCONTRADO
        
        📦 [Título]
        ASIN: B07XYZ123
        
        💰 FINANCIERO
        Precio Amazon: €45.99
        Margen: €27.49
        ROI: 148%
        
        ⚙️ ANÁLISIS
        Score: 82/100
        Competencia FBA: 6 vendedores
        
        ✅ EXCELENTE - Compra inmediatamente
        """
        
        # Color por recomendación
        emoji = "✅" if alert.score >= 75 else "⚠️" if alert.score >= 50 else "❌"
        color_score = alert.recommendation
        
        # Score visual
        filled = (alert.score // 10)
        empty = 10 - filled
        score_bar = "█" * filled + "░" * empty
        
        text = f"""
🎯 VIABLE ENCONTRADO

📦 <b>{alert.title[:80]}</b>
<code>{alert.asin}</code>

💰 FINANCIERO
├─ Precio Amazon: €{alert.price:.2f}
├─ Costo mínimo: €{alert.cost:.2f}
├─ <b>Margen: €{alert.margin:.2f}</b>
└─ <b>ROI: {alert.roi:.0f}%</b>

📊 COMPETENCIA
├─ Score: {score_bar} {alert.score}/100
├─ Vendedores FBA: {alert.fba_competitors}
├─ Categoría: {alert.category}
└─ Recomendación: <b>{color_score}</b>

<b>{emoji} {color_score}</b>
""".strip()
        
        await self._ensure_session()
        
        # Crear botones inline
        buttons = []
        
        if alert.score >= 75:
            buttons.append({
                "text": "✅ COMPRA",
                "callback_data": f"buy_{alert.asin}"
            })
        
        if alert.score >= 50:
            buttons.append({
                "text": "⚠️ REVISAR",
                "callback_data": f"review_{alert.asin}"
            })
        
        buttons.append({
            "text": "❌ PASO",
            "callback_data": f"skip_{alert.asin}"
        })
        
        buttons.append({
            "text": "🔗 Link",
            "url": f"https://amazon.es/dp/{alert.asin}"
        })
        
        # Agrupar botones (2 por fila)
        inline_keyboard = []
        for i in range(0, len(buttons), 2):
            inline_keyboard.append(buttons[i:i+2])
        
        try:
            async with self.session.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": inline_keyboard
                    },
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    message_id = data.get("result", {}).get("message_id")
                    log.info("telegram.alert_sent", asin=alert.asin, message_id=message_id)
                    return True
                else:
                    log.error("telegram.alert_failed", status=resp.status, asin=alert.asin)
                    return False
        except Exception as e:
            log.error("telegram.alert_error", error=str(e), asin=alert.asin)
            return False
    
    def on_callback(self, callback_data: str, handler: Callable):
        """Registrar handler para callback"""
        self._callbacks[callback_data] = handler
    
    async def handle_callback(self, query_id: str, callback_data: str, callback_answer: str = "✓"):
        """Responder a click de botón"""
        try:
            await self._ensure_session()
            
            async with self.session.post(
                f"{self.api_url}/answerCallbackQuery",
                json={
                    "callback_query_id": query_id,
                    "text": callback_answer,
                    "show_alert": False,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    log.info("telegram.callback_answered", callback=callback_data)
                    return True
                else:
                    log.error("telegram.callback_failed", status=resp.status)
                    return False
        except Exception as e:
            log.error("telegram.callback_error", error=str(e))
            return False
    
    async def get_updates(self, offset: int = 0, timeout: int = 30) -> list[dict]:
        """Long polling para recibir updates (botones presionados)"""
        try:
            await self._ensure_session()
            
            async with self.session.get(
                f"{self.api_url}/getUpdates",
                params={
                    "offset": offset,
                    "timeout": timeout,
                    "allowed_updates": ["callback_query"],
                },
                timeout=aiohttp.ClientTimeout(total=timeout + 5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("result", [])
                else:
                    return []
        except Exception as e:
            log.error("telegram.get_updates_error", error=str(e))
            return []
    
    async def send_daily_summary(
        self,
        products_found: int,
        products_viable: int,
        top_scores: list[tuple[str, int]],
    ) -> bool:
        """Enviar resumen diario"""
        
        top_text = "\n".join([
            f"  {i+1}. {asin}: {score}/100"
            for i, (asin, score) in enumerate(top_scores[:5])
        ])
        
        text = f"""
📊 RESUMEN DIARIO

📦 Productos analizados: {products_found}
✅ Viables encontrados: {products_viable}

🏆 Top Scores:
{top_text}

Próxima búsqueda en 4h...
""".strip()
        
        return await self.send_message(text)
