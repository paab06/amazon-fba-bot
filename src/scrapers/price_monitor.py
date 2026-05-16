# src/scrapers/price_monitor.py
"""
Price Monitor — Monitoreo Continuo de Precios y BSR

Responsabilidades:
  - Monitorear precios de productos (lista observada)
  - Trackear cambios de BSR
  - Detectar anomalías (price drops, restocks)
  - Generar alertas de oportunidades
  - Persistir históricos
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from redis.asyncio import Redis

from src.api.keepa_client import KeepaClient
from src.api.sp_api_client import SPAPIClient
from src.core.exceptions import SPAPINotFoundError

log = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class PriceSnapshot:
    """Snapshot de precio en un momento dado"""
    asin: str
    timestamp: datetime
    current_price: float
    bsr_rank: int
    stock_level: int
    buybox_seller: str
    buybox_is_fba: bool


@dataclass(slots=True)
class PriceAlert:
    """Alerta de cambio significativo"""
    asin: str
    alert_type: str  # price_drop, price_surge, bsr_drop, restock
    previous_value: float
    current_value: float
    change_pct: float
    timestamp: datetime
    action_suggested: str  # BUY_NOW, WAIT, SKIP


class PriceMonitor:
    """
    Monitorea lista de productos (watchlist).
    
    Uso:
        monitor = PriceMonitor(sp_client, keepa_client, redis)
        await monitor.add_to_watchlist(["B07XYZ123", "B08ABC456"])
        alerts = await monitor.check_watchlist()
        for alert in alerts:
            print(f"{alert.alert_type}: {alert.asin}")
    """

    def __init__(
        self,
        sp_client: SPAPIClient,
        keepa_client: KeepaClient,
        redis: Redis,
    ) -> None:
        """
        Args:
            sp_client: Cliente SP-API
            keepa_client: Cliente Keepa
            redis: Conexión Redis para persistencia
        """
        self._sp = sp_client
        self._keepa = keepa_client
        self._redis = redis
        self._watchlist_key = "monitor:watchlist"
        self._snapshot_prefix = "monitor:snapshot:"
        self._alert_queue_key = "monitor:alerts"

    async def add_to_watchlist(self, asins: list[str]) -> None:
        """
        Agrega ASINs a la lista de monitoreo.
        
        Args:
            asins: Lista de ASINs a monitorear
        """
        log.info("price_monitor.add_watchlist", count=len(asins))
        
        for asin in asins:
            await self._redis.sadd(self._watchlist_key, asin)

    async def remove_from_watchlist(self, asins: list[str]) -> None:
        """Elimina ASINs de la lista de monitoreo"""
        for asin in asins:
            await self._redis.srem(self._watchlist_key, asin)
        
        log.info("price_monitor.remove_watchlist", count=len(asins))

    async def get_watchlist(self) -> set[str]:
        """Obtiene lista actual de ASINs monitoreados"""
        asins = await self._redis.smembers(self._watchlist_key)
        return {asin.decode() if isinstance(asin, bytes) else asin for asin in asins}

    async def take_snapshot(self, asin: str) -> Optional[PriceSnapshot]:
        """
        Captura snapshot actual de un ASIN.
        
        Args:
            asin: ASIN a capturar
            
        Returns:
            PriceSnapshot con datos actuales
        """
        try:
            offers = await self._sp.get_item_offers(asin=asin)
            
            if not offers:
                return None

            snapshot = PriceSnapshot(
                asin=asin,
                timestamp=datetime.now(timezone.utc),
                current_price=offers.get("buybox_price", 0),
                bsr_rank=offers.get("bsr", 999999),
                stock_level=offers.get("stock", 0),
                buybox_seller=offers.get("buybox_seller", "Unknown"),
                buybox_is_fba=offers.get("buybox_is_fba", False),
            )
            
            # Persistir en Redis
            key = f"{self._snapshot_prefix}{asin}"
            await self._redis.set(
                key,
                snapshot.__repr__(),
                ex=7 * 24 * 60 * 60,  # 7 días TTL
            )
            
            return snapshot

        except SPAPINotFoundError:
            log.warning("price_monitor.asin_not_found", asin=asin)
            return None
        except Exception as exc:
            log.error("price_monitor.snapshot_error", asin=asin, error=str(exc))
            return None

    async def check_watchlist(self) -> list[PriceAlert]:
        """
        Verifica toda la watchlist y genera alertas.
        
        Returns:
            Lista de PriceAlert
            
        Detecta:
        - Caída de precio >= 10%
        - Aumento de precio >= 15%
        - Caída de BSR >= 20%
        - Restock detectado
        """
        log.info("price_monitor.check_watchlist")
        
        watchlist = await self.get_watchlist()
        alerts = []

        for asin in watchlist:
            try:
                # Obtener snapshot actual
                current = await self.take_snapshot(asin)
                if not current:
                    continue

                # Obtener snapshot anterior (de Redis)
                previous = await self._get_previous_snapshot(asin)
                if not previous:
                    # Primera captura, solo registrar
                    continue

                # Comparar y generar alertas
                alerts.extend(
                    await self._generate_alerts(asin, previous, current)
                )

            except Exception as exc:
                log.warning(
                    "price_monitor.check_error",
                    asin=asin,
                    error=str(exc),
                )
                continue

        # Persistir alertas en Redis queue
        for alert in alerts:
            await self._redis.lpush(self._alert_queue_key, alert.__repr__())

        log.info("price_monitor.check_complete", alert_count=len(alerts))
        return alerts

    async def _get_previous_snapshot(self, asin: str) -> Optional[PriceSnapshot]:
        """Obtiene snapshot anterior de Redis"""
        key = f"{self._snapshot_prefix}{asin}:prev"
        data = await self._redis.get(key)
        
        if data:
            # Parse snapshot (simplificado)
            # En producción, usar JSON serialization
            try:
                # Placeholder: retornar None si no está completo
                return None
            except Exception:
                return None
        return None

    async def _generate_alerts(
        self,
        asin: str,
        previous: PriceSnapshot,
        current: PriceSnapshot,
    ) -> list[PriceAlert]:
        """Genera alertas comparando snapshots"""
        alerts = []

        # ── Detectar caída de precio ───────────────────────────────────
        if current.current_price > 0 and previous.current_price > 0:
            price_change_pct = (
                (previous.current_price - current.current_price)
                / previous.current_price
                * 100
            )

            if price_change_pct >= 10:
                alerts.append(
                    PriceAlert(
                        asin=asin,
                        alert_type="price_drop",
                        previous_value=previous.current_price,
                        current_value=current.current_price,
                        change_pct=price_change_pct,
                        timestamp=datetime.now(timezone.utc),
                        action_suggested="BUY_NOW"
                        if price_change_pct >= 20
                        else "CONSIDER",
                    )
                )

            elif price_change_pct <= -15:
                alerts.append(
                    PriceAlert(
                        asin=asin,
                        alert_type="price_surge",
                        previous_value=previous.current_price,
                        current_value=current.current_price,
                        change_pct=abs(price_change_pct),
                        timestamp=datetime.now(timezone.utc),
                        action_suggested="WAIT",
                    )
                )

        # ── Detectar caída de BSR ──────────────────────────────────────
        if previous.bsr_rank > 0 and current.bsr_rank > 0:
            bsr_change_pct = (
                (previous.bsr_rank - current.bsr_rank) / previous.bsr_rank * 100
            )

            if bsr_change_pct >= 20:  # BSR mejoró (número más bajo)
                alerts.append(
                    PriceAlert(
                        asin=asin,
                        alert_type="bsr_improvement",
                        previous_value=float(previous.bsr_rank),
                        current_value=float(current.bsr_rank),
                        change_pct=bsr_change_pct,
                        timestamp=datetime.now(timezone.utc),
                        action_suggested="MONITOR",
                    )
                )

        # ── Detectar restock ───────────────────────────────────────────
        if (
            previous.stock_level < 50
            and current.stock_level >= 100
        ):
            alerts.append(
                PriceAlert(
                    asin=asin,
                    alert_type="restock_detected",
                    previous_value=float(previous.stock_level),
                    current_value=float(current.stock_level),
                    change_pct=100,
                    timestamp=datetime.now(timezone.utc),
                    action_suggested="BUY_OPPORTUNITY",
                )
            )

        return alerts

    async def get_historical_data(
        self,
        asin: str,
        days: int = 30,
    ) -> list[PriceSnapshot]:
        """
        Obtiene histórico de precios de los últimos N días.
        
        Args:
            asin: ASIN a analizar
            days: Cantidad de días hacia atrás
            
        Returns:
            Lista ordenada de snapshots por fecha
            
        Nota: Requiere Keepa para históricos completos
        """
        log.info(
            "price_monitor.get_history",
            asin=asin,
            days=days,
        )

        try:
            history = await self._keepa.get_price_history(
                asin=asin,
                days=days,
            )
            
            # Convertir a list de PriceSnapshot
            snapshots = []
            for item in history:
                snap = PriceSnapshot(
                    asin=asin,
                    timestamp=item.get("timestamp"),
                    current_price=item.get("price", 0),
                    bsr_rank=item.get("bsr", 999999),
                    stock_level=item.get("stock", 0),
                    buybox_seller=item.get("seller", "Unknown"),
                    buybox_is_fba=item.get("is_fba", False),
                )
                snapshots.append(snap)
            
            return snapshots

        except Exception as exc:
            log.error(
                "price_monitor.history_error",
                asin=asin,
                error=str(exc),
            )
            return []

    async def get_pending_alerts(self) -> list[PriceAlert]:
        """Obtiene alertas pendientes del queue"""
        alerts = []
        
        while True:
            alert_data = await self._redis.rpop(self._alert_queue_key)
            if not alert_data:
                break
            
            # Parse alert (simplificado)
            alerts.append(alert_data)
        
        return alerts
