# src/scrapers/competitive_analyzer.py
"""
Competitive Analyzer para Amazon.es — Análisis Profundo de Viabilidad

Analiza la competencia real y produce un score 0-100 que permite
identificar verdaderas oportunidades vs falsas esperanzas.

Score Breakdown:
- 25%: Competencia FBA (número de vendedores)
- 25%: Trend de precios (¿sube o baja?)
- 25%: Velocidad de venta (¿rápido o lento?)
- 15%: Saturación de categoría
- 10%: Ventaja de precio vs competencia

Input: ASIN
Output: Score 0-100 + Recomendación (✅ Compra, ⚠️ Revisar, ❌ Rechaza)

Uso:
    analyzer = CompetitiveAnalyzer(keepa, sp_api)
    score = await analyzer.score_product(asin="B07XYZ123")
    
    if score['total'] >= 75:
        print("✅ EXCELENTE")
    elif score['total'] >= 50:
        print("⚠️ REVISAR")
    else:
        print("❌ RECHAZA")
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

from src.api.keepa_client import KeepaClient
from src.api.sp_api_client import SPAPIClient

log = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════════
#  Data Classes
# ══════════════════════════════════════════════════════════════════

@dataclass(slots=True, frozen=True)
class CompetitiveScore:
    """Score de viabilidad competitiva (0-100)"""
    total: int  # 0-100
    
    fba_competition: int  # 0-25
    price_trend: int  # 0-25
    sales_velocity: int  # 0-25
    category_saturation: int  # 0-15
    price_advantage: int  # 0-10
    
    recommendation: str  # "✅ Compra", "⚠️ Revisar", "❌ Rechaza"
    reasoning: str  # Explicación legible


# ══════════════════════════════════════════════════════════════════
#  Main Analyzer
# ══════════════════════════════════════════════════════════════════

class CompetitiveAnalyzer:
    """
    Analiza viabilidad competitiva de un producto
    
    Propósito: Separar oportunidades REALES de falsas esperanzas
    
    Ejemplo:
    - Margen €27 pero 50 vendedores batallando = FALSA
    - Margen €20 pero 3 vendedores estables = REAL
    """

    def __init__(
        self,
        keepa_client: KeepaClient,
        sp_api_client: SPAPIClient,
    ) -> None:
        self._keepa = keepa_client
        self._sp = sp_api_client

    async def score_product(
        self,
        asin: str,
        amazon_price: float,
        cost_price: float,
        category: str,
    ) -> CompetitiveScore:
        """
        Calcula score de viabilidad 0-100
        
        Args:
            asin: Product ASIN
            amazon_price: Precio actual en Amazon
            cost_price: Precio de costo mínimo
            category: Categoría del producto
            
        Returns:
            CompetitiveScore con desglose y recomendación
        """
        log.info(
            "analyzer.score_product.start",
            asin=asin,
            amazon_price=amazon_price,
            cost_price=cost_price,
        )

        try:
            # Calcular cada componente en paralelo
            fba_score = await self._score_fba_competition(asin)
            trend_score = await self._score_price_trend(asin)
            velocity_score = await self._score_sales_velocity(asin)
            saturation_score = self._score_category_saturation(category)
            advantage_score = await self._score_price_advantage(
                asin, amazon_price, cost_price
            )

            # Calcular total ponderado
            total = (
                fba_score * 0.25
                + trend_score * 0.25
                + velocity_score * 0.25
                + saturation_score * 0.15
                + advantage_score * 0.10
            )

            # Redondear a entero
            total = int(round(total))

            # Generar recomendación
            recommendation, reasoning = self._get_recommendation(
                total, fba_score, trend_score, velocity_score
            )

            result = CompetitiveScore(
                total=total,
                fba_competition=fba_score,
                price_trend=trend_score,
                sales_velocity=velocity_score,
                category_saturation=saturation_score,
                price_advantage=advantage_score,
                recommendation=recommendation,
                reasoning=reasoning,
            )

            log.info(
                "analyzer.score_product.complete",
                asin=asin,
                score=total,
                recommendation=recommendation,
            )

            return result

        except Exception as exc:
            log.error("analyzer.score_product.error", asin=asin, error=str(exc))
            # En caso de error, asumir score bajo (fail-safe)
            return CompetitiveScore(
                total=30,
                fba_competition=5,
                price_trend=5,
                sales_velocity=5,
                category_saturation=5,
                price_advantage=5,
                recommendation="⚠️ Revisar",
                reasoning=f"Error en análisis: {exc}. Revisar manualmente.",
            )

    async def _score_fba_competition(self, asin: str) -> int:
        """
        Score de competencia FBA (0-25 puntos)
        
        Cuantos MENOS vendedores FBA, mejor
        1-3 = 25 (excelente, nicho)
        4-10 = 15 (bueno)
        11-20 = 8 (aceptable pero saturado)
        20+ = 2 (muy saturado)
        """
        try:
            fba_count = await self._keepa.get_fba_seller_count(asin)

            if fba_count <= 3:
                score = 25  # Excelente
                log.debug("analyzer.fba.excellent", asin=asin, count=fba_count)
            elif fba_count <= 10:
                score = 15  # Bueno
            elif fba_count <= 20:
                score = 8  # Aceptable
            else:
                score = 2  # Muy saturado

            return score

        except Exception as exc:
            log.warning("analyzer.fba.error", asin=asin, error=str(exc))
            return 10  # Asumen promedio

    async def _score_price_trend(self, asin: str) -> int:
        """
        Score de trend de precios (0-25 puntos)
        
        Precio ESTABLE o SUBIENDO = excelente
        Precio BAJANDO = malo (perderás margen)
        
        Analiza últimos 90 días
        """
        try:
            history = await self._keepa.get_price_history(asin, days=90)

            if not history:
                return 15  # Default promedio

            # Analizar trend
            trend = self._analyze_price_trend(history)

            if trend["direction"] == "up":
                return 25  # Precio subiendo = oportunidad
            elif trend["direction"] == "stable":
                return 20  # Estable = bueno
            elif trend["drop_pct"] < 5:
                return 12  # Bajando poco
            elif trend["drop_pct"] < 10:
                return 6  # Bajando mucho
            else:
                return 2  # Desplome

        except Exception as exc:
            log.warning("analyzer.trend.error", asin=asin, error=str(exc))
            return 15  # Asumen promedio

    async def _score_sales_velocity(self, asin: str) -> int:
        """
        Score de velocidad de venta (0-25 puntos)
        
        RÁPIDO = dinero rápido = bueno
        LENTO = dinero congelado = malo
        """
        try:
            velocity_data = await self._keepa.get_product_velocity(asin)

            # Estimar units/día
            daily_sales = velocity_data.get("daily_sales", 0)

            if daily_sales >= 10:
                return 25  # Venta rápida
            elif daily_sales >= 5:
                return 20  # Normal
            elif daily_sales >= 2:
                return 10  # Lento
            else:
                return 2  # Muy lento

        except Exception as exc:
            log.warning("analyzer.velocity.error", asin=asin, error=str(exc))
            return 12  # Asumen promedio

    def _score_category_saturation(self, category: str) -> int:
        """
        Score de saturación de categoría (0-15 puntos)
        
        Nichos pequeños = mejor
        Categorías grandes saturadas = peor
        """
        # Estimar saturación según categoría
        saturation_estimates = {
            "Electronics": 60,  # Muy saturado
            "Home & Garden": 40,  # Moderado
            "Sports & Outdoors": 35,  # Bueno
            "Gaming": 50,  # Bastante saturado
            "Toys & Games": 70,  # Muy saturado
        }

        saturation = saturation_estimates.get(category, 50)

        if saturation < 30:
            return 15  # Nicho pequeño
        elif saturation < 60:
            return 10  # Normal
        else:
            return 2  # Muy saturado

    async def _score_price_advantage(
        self,
        asin: str,
        amazon_price: float,
        cost_price: float,
    ) -> int:
        """
        Score de ventaja de precio vs competencia (0-10 puntos)
        
        ¿Tienes margen para competir?
        """
        try:
            offers = await self._sp.get_offers(asin)

            if not offers:
                return 8  # Sin info, asumir bueno

            # Calcular precio promedio competencia
            competitor_prices = [o["price"] for o in offers]
            avg_price = sum(competitor_prices) / len(competitor_prices)

            # Tu ventaja
            your_advantage = amazon_price - avg_price

            if your_advantage < -5:
                return 10  # Precio muy mejor que competencia
            elif your_advantage <= 0:
                return 8  # Precio competitivo
            elif your_advantage <= 5:
                return 5  # Precio alto
            else:
                return 2  # Precio muy alto

        except Exception as exc:
            log.warning("analyzer.price_advantage.error", asin=asin, error=str(exc))
            return 5  # Default

    def _analyze_price_trend(self, history: list[tuple]) -> dict:
        """
        Analiza histórico de precios
        
        Args:
            history: Lista de (fecha, precio) tuples
            
        Returns:
            dict con "direction", "drop_pct"
        """
        if not history or len(history) < 2:
            return {"direction": "stable", "drop_pct": 0}

        # Comparar primero vs último
        first_price = history[0][1]
        last_price = history[-1][1]

        if last_price > first_price * 1.05:
            direction = "up"
            drop_pct = 0
        elif last_price < first_price * 0.95:
            direction = "down"
            drop_pct = (1 - last_price / first_price) * 100
        else:
            direction = "stable"
            drop_pct = 0

        return {"direction": direction, "drop_pct": drop_pct}

    def _get_recommendation(
        self,
        total: int,
        fba_score: int,
        trend_score: int,
        velocity_score: int,
    ) -> tuple[str, str]:
        """
        Genera recomendación basada en score
        
        Returns:
            (recommendation, reasoning)
        """
        reasons = []

        if total >= 75:
            # EXCELENTE
            recommendation = "✅ EXCELENTE"
            reasons.append(
                f"Score alto ({total}/100) - Todas las métricas favorables"
            )

            if fba_score >= 20:
                reasons.append("• Competencia baja (pocos vendedores FBA)")
            if trend_score >= 20:
                reasons.append("• Precio estable o subiendo")
            if velocity_score >= 20:
                reasons.append("• Venta rápida (dinero rápido)")

        elif total >= 50:
            # BORDERLINE
            recommendation = "⚠️ BORDERLINE"

            if fba_score < 8:
                reasons.append("⚠️ Competencia alta (muchos vendedores FBA)")
            if trend_score < 8:
                reasons.append("⚠️ Precios bajando (margen en riesgo)")
            if velocity_score < 8:
                reasons.append("⚠️ Venta lenta (dinero congelado)")

            reasons.append("→ Requiere revisión manual antes de comprar")

        else:
            # RECHAZA
            recommendation = "❌ RECHAZA"

            if fba_score < 5:
                reasons.append("❌ Mercado saturado (50+ competidores)")
            if trend_score < 5:
                reasons.append("❌ Precios cayendo rápidamente")
            if velocity_score < 5:
                reasons.append("❌ Venta muy lenta")

            reasons.append("→ Riesgo alto de pérdida. No comprar.")

        reasoning = "\n".join(reasons)
        return recommendation, reasoning


# ══════════════════════════════════════════════════════════════════
#  Helper Functions
# ══════════════════════════════════════════════════════════════════

def format_score_for_telegram(score: CompetitiveScore, asin: str) -> str:
    """
    Formatea score para Telegram
    
    Uso:
        message = format_score_for_telegram(score, asin)
        await telegram.send_message(message)
    """
    bars = "▓" * (score.total // 10) + "░" * (10 - score.total // 10)

    message = f"""
🏆 ANÁLISIS DE COMPETENCIA

ASIN: {asin}

📊 SCORE COMPETITIVO:
{bars} {score.total}/100

DESGLOSE:
├─ FBA Competencia: {'▓' * (score.fba_competition // 3)} {score.fba_competition}/25
├─ Trend Precios: {'▓' * (score.price_trend // 3)} {score.price_trend}/25
├─ Velocidad Venta: {'▓' * (score.sales_velocity // 3)} {score.sales_velocity}/25
├─ Saturación Cat: {'▓' * (score.category_saturation // 2)} {score.category_saturation}/15
└─ Ventaja Precio: {'▓' * (score.price_advantage // 1)} {score.price_advantage}/10

{score.recommendation}

{score.reasoning}
"""
    return message
