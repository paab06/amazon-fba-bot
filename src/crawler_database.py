"""
Database tracking para crawler

Guarda:
- Productos analizados
- Viables encontrados
- ROI predicho vs real
- Histórico de alertas
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import asyncpg
import structlog

log = structlog.get_logger(__name__)


class CrawlerDatabase:
    """
    Persistencia de datos del crawler
    
    Tablas:
    - products_analyzed: Histórico de todos analizados
    - viable_products: Los que pasaron todos filtros
    - alerts_sent: Alertas enviadas a Telegram
    - roi_tracking: ROI predicho vs real después de venta
    """
    
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        """Conectar a DB y crear tablas si no existen"""
        self.pool = await asyncpg.create_pool(self.dsn)
        await self._create_tables()
        log.info("crawler_db.connected")
    
    async def disconnect(self):
        """Desconectar"""
        if self.pool:
            await self.pool.close()
            log.info("crawler_db.disconnected")
    
    async def _create_tables(self):
        """Crear tablas si no existen"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS products_analyzed (
                    id SERIAL PRIMARY KEY,
                    asin VARCHAR(20) NOT NULL,
                    title VARCHAR(255),
                    category VARCHAR(100),
                    price_amazon NUMERIC(10, 2),
                    cost_min NUMERIC(10, 2),
                    margin NUMERIC(10, 2),
                    roi NUMERIC(10, 2),
                    crawl_type VARCHAR(50),
                    analyzed_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(asin, analyzed_at)
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS viable_products (
                    id SERIAL PRIMARY KEY,
                    asin VARCHAR(20) NOT NULL UNIQUE,
                    title VARCHAR(255),
                    price_amazon NUMERIC(10, 2),
                    margin NUMERIC(10, 2),
                    roi NUMERIC(10, 2),
                    score INTEGER,
                    recommendation VARCHAR(50),
                    status VARCHAR(20),
                    found_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts_sent (
                    id SERIAL PRIMARY KEY,
                    asin VARCHAR(20) NOT NULL,
                    message_text TEXT,
                    telegram_message_id INTEGER,
                    score INTEGER,
                    sent_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS roi_tracking (
                    id SERIAL PRIMARY KEY,
                    asin VARCHAR(20) NOT NULL,
                    roi_predicted NUMERIC(10, 2),
                    roi_actual NUMERIC(10, 2),
                    units_sold INTEGER,
                    sale_price NUMERIC(10, 2),
                    cost_actual NUMERIC(10, 2),
                    status VARCHAR(20),
                    purchased_at TIMESTAMP,
                    sold_out_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            log.info("crawler_db.tables_created")
    
    async def log_product_analyzed(
        self,
        asin: str,
        title: str,
        category: str,
        price: float,
        cost: float,
        margin: float,
        roi: float,
        crawl_type: str,
    ) -> bool:
        """Guardar producto analizado"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO products_analyzed
                    (asin, title, category, price_amazon, cost_min, margin, roi, crawl_type)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT DO NOTHING
                """, asin, title, category, price, cost, margin, roi, crawl_type)
            
            log.info("crawler_db.logged_analyzed", asin=asin)
            return True
        except Exception as e:
            log.error("crawler_db.log_error", error=str(e))
            return False
    
    async def log_viable_found(
        self,
        asin: str,
        title: str,
        price: float,
        margin: float,
        roi: float,
        score: int,
        recommendation: str,
    ) -> bool:
        """Guardar viable encontrado"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO viable_products
                    (asin, title, price_amazon, margin, roi, score, recommendation, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'found')
                    ON CONFLICT (asin) DO UPDATE SET
                        updated_at = NOW()
                """, asin, title, price, margin, roi, score, recommendation)
            
            log.info("crawler_db.logged_viable", asin=asin, score=score)
            return True
        except Exception as e:
            log.error("crawler_db.viable_error", error=str(e))
            return False
    
    async def log_alert_sent(
        self,
        asin: str,
        message_text: str,
        telegram_message_id: Optional[int],
        score: int,
    ) -> bool:
        """Guardar alert enviada"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO alerts_sent
                    (asin, message_text, telegram_message_id, score)
                    VALUES ($1, $2, $3, $4)
                """, asin, message_text, telegram_message_id, score)
            
            log.info("crawler_db.logged_alert", asin=asin)
            return True
        except Exception as e:
            log.error("crawler_db.alert_error", error=str(e))
            return False
    
    async def mark_product_purchased(self, asin: str) -> bool:
        """Marcar viable como comprado"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE viable_products
                    SET status = 'purchased', updated_at = NOW()
                    WHERE asin = $1
                """, asin)
            
            log.info("crawler_db.marked_purchased", asin=asin)
            return True
        except Exception as e:
            log.error("crawler_db.purchase_error", error=str(e))
            return False
    
    async def track_roi(
        self,
        asin: str,
        roi_predicted: float,
        roi_actual: Optional[float] = None,
        units_sold: Optional[int] = None,
        status: str = "pending",
    ) -> bool:
        """Trackear ROI predicho vs real"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO roi_tracking
                    (asin, roi_predicted, roi_actual, units_sold, status, purchased_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    ON CONFLICT (asin) DO UPDATE SET
                        roi_actual = COALESCE($3, roi_actual),
                        units_sold = COALESCE($4, units_sold),
                        status = $5,
                        sold_out_at = CASE WHEN $5 = 'sold_out' THEN NOW() ELSE sold_out_at END
                """, asin, roi_predicted, roi_actual, units_sold, status)
            
            log.info("crawler_db.tracked_roi", asin=asin)
            return True
        except Exception as e:
            log.error("crawler_db.roi_error", error=str(e))
            return False
    
    async def get_viable_products(self, status: str = "found") -> list[dict]:
        """Obtener viables con estado específico"""
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM viable_products
                    WHERE status = $1
                    ORDER BY score DESC
                    LIMIT 100
                """, status)
            
            return [dict(row) for row in rows]
        except Exception as e:
            log.error("crawler_db.get_error", error=str(e))
            return []
    
    async def get_stats(self) -> dict:
        """Obtener estadísticas generales"""
        try:
            async with self.pool.acquire() as conn:
                analyzed = await conn.fetchval("""
                    SELECT COUNT(*) FROM products_analyzed
                    WHERE analyzed_at > NOW() - INTERVAL '24 hours'
                """)
                
                viable = await conn.fetchval("""
                    SELECT COUNT(*) FROM viable_products
                    WHERE found_at > NOW() - INTERVAL '24 hours'
                """)
                
                alerts = await conn.fetchval("""
                    SELECT COUNT(*) FROM alerts_sent
                    WHERE sent_at > NOW() - INTERVAL '24 hours'
                """)
                
                avg_roi = await conn.fetchval("""
                    SELECT AVG(roi_actual) FROM roi_tracking
                    WHERE sold_out_at > NOW() - INTERVAL '30 days'
                    AND roi_actual IS NOT NULL
                """)
                
                return {
                    "analyzed_24h": analyzed or 0,
                    "viable_found_24h": viable or 0,
                    "alerts_sent_24h": alerts or 0,
                    "avg_roi_actual": float(avg_roi or 0),
                }
        except Exception as e:
            log.error("crawler_db.stats_error", error=str(e))
            return {}
