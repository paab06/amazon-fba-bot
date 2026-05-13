# src/pipeline/ingestor.py
"""
Ingestor — lee el archivo CSV de productos y emite
ProductInput al pipeline. Valida tipos y descarta filas
malformadas sin detener el proceso.
"""
from __future__ import annotations

import csv
import aiofiles
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProductInput:
    ean: str
    buy_price: float
    source_row: int   # nº de fila original para trazabilidad


async def read_csv(path: str | Path) -> AsyncIterator[ProductInput]:
    """
    Generador asíncrono que emite ProductInput fila a fila.
    Salta silenciosamente filas con EAN vacío o precio inválido
    y lo registra en el log para revisión posterior.

    Formato CSV esperado (cabecera obligatoria):
        ean,buy_price
        5901234123457,12.50
        4006381333931,8.00
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV no encontrado: {path}")

    async with aiofiles.open(path, mode="r", encoding="utf-8-sig") as f:
        content = await f.read()

    # csv no es async-nativo, lo procesamos en memoria tras la lectura
    reader = csv.DictReader(content.splitlines())

    required = {"ean", "buy_price"}
    if not reader.fieldnames or not required.issubset(
        {c.strip().lower() for c in reader.fieldnames}
    ):
        raise ValueError(
            f"El CSV debe tener las columnas: {required}. "
            f"Encontradas: {reader.fieldnames}"
        )

    for row_num, row in enumerate(reader, start=2):  # start=2: fila 1 es cabecera
        ean = row.get("ean", "").strip()
        raw_price = row.get("buy_price", "").strip().replace(",", ".")

        if not ean:
            log.warning("ingestor.skip.empty_ean", row=row_num)
            continue

        try:
            buy_price = float(raw_price)
            if buy_price <= 0:
                raise ValueError("precio negativo o cero")
        except (ValueError, TypeError):
            log.warning(
                "ingestor.skip.invalid_price",
                row=row_num,
                ean=ean,
                raw=raw_price,
            )
            continue

        yield ProductInput(ean=ean, buy_price=buy_price, source_row=row_num)