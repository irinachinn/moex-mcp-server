"""
MOEX ISS MCP Server
Анализ акций, облигаций и ETF на Московской бирже через публичный ISS API.
"""

import json
import httpx
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("moex_mcp")

BASE_URL = "https://iss.moex.com/iss"
HEADERS = {"Accept": "application/json", "User-Agent": "moex-mcp/1.0"}
TIMEOUT = 15.0


# ─── Shared HTTP client ───────────────────────────────────────────────────────

async def moex_get(path: str, params: dict = None) -> dict:
    """Выполняет GET-запрос к MOEX ISS API и возвращает JSON."""
    url = f"{BASE_URL}{path}.json"
    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT) as client:
        resp = client.get(url, params=params or {})
        resp = await resp if hasattr(resp, "__await__") else resp
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT) as c:
                r = await c.get(url, params=params or {})
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            raise ValueError(f"MOEX API вернул {e.response.status_code}: {e.response.text[:200]}")
        except httpx.TimeoutException:
            raise ValueError("Таймаут запроса к MOEX ISS API. Попробуйте позже.")


async def _get(path: str, params: dict = None) -> dict:
    """Прямой async GET к MOEX ISS."""
    url = f"{BASE_URL}{path}.json"
    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT) as c:
        r = await c.get(url, params=params or {})
        r.raise_for_status()
        return r.json()


def _rows(data: dict, block: str) -> list[dict]:
    """Преобразует ответ ISS (columns + data) в список словарей."""
    block_data = data.get(block, {})
    cols = block_data.get("columns", [])
    rows = block_data.get("data", [])
    return [dict(zip(cols, row)) for row in rows]


def _fmt(value, decimals: int = 2) -> str:
    """Форматирует число или возвращает '—' для None."""
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


# ─── Input Models ─────────────────────────────────────────────────────────────

class TickerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    ticker: str = Field(..., description="Тикер бумаги на MOEX, например SBER, LKOH, SU26238RMFS3", min_length=1, max_length=36)


class SecuritySearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(..., description="Поисковый запрос: название или часть тикера", min_length=1, max_length=100)
    limit: Optional[int] = Field(default=10, description="Максимум результатов (1–50)", ge=1, le=50)


class DividendsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    ticker: str = Field(..., description="Тикер акции, например SBER, LKOH, GAZP", min_length=1, max_length=12)


class IndexInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    index: str = Field(default="IMOEX", description="Индекс MOEX: IMOEX, RTSI, MOEXBC и др.")


class CandlesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    ticker: str = Field(..., description="Тикер бумаги, например SBER", min_length=1, max_length=12)
    interval: int = Field(default=24, description="Интервал свечей в часах: 1, 4, 24 (день), 168 (неделя)", ge=1)
    limit: Optional[int] = Field(default=30, description="Количество свечей (1–200)", ge=1, le=200)


class ObligationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    ticker: str = Field(..., description="Тикер облигации, например SU26238RMFS3, RU000A105QH6", min_length=1, max_length=36)


# ─── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="moex_get_security_info",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def moex_get_security_info(params: TickerInput) -> str:
    """Получить базовую информацию о ценной бумаге на MOEX.

    Возвращает: ISIN, полное название, тип бумаги, рынок, лотность,
    номинал, статус листинга, дату начала торгов.

    Args:
        params: TickerInput с полем ticker (str)

    Returns:
        str: Markdown-форматированная карточка бумаги
    """
    ticker = params.ticker.upper()
    try:
        data = await _get(f"/securities/{ticker}")
    except Exception as e:
        return f"Ошибка: {e}"

    desc = _rows(data, "description")
    boards = _rows(data, "boards")

    if not desc:
        return f"Бумага {ticker} не найдена на MOEX."

    info = {row["name"]: row["value"] for row in desc}

    primary = next((b for b in boards if b.get("is_primary") == 1), boards[0] if boards else {})

    lines = [
        f"## {ticker} — {info.get('NAME', '—')}",
        f"**Краткое название:** {info.get('SHORTNAME', '—')}",
        f"**ISIN:** {info.get('ISIN', '—')}",
        f"**Тип:** {info.get('TYPE', '—')} / {info.get('GROUP', '—')}",
        f"**Эмитент:** {info.get('ISSUERID', '—')}",
        f"**Номинал:** {_fmt(info.get('FACEVALUE'))} {info.get('FACEUNIT', 'RUB')}",
        f"**Объём эмиссии:** {info.get('ISSUESIZE', '—')}",
        f"**Статус:** {info.get('STATUS', '—')}",
        f"**Начало торгов:** {info.get('LISTINGDATE', '—')}",
    ]
    if primary:
        lines += [
            f"\n### Основная площадка",
            f"**Рынок:** {primary.get('boardid', '—')} ({primary.get('market', '—')})",
            f"**Движок:** {primary.get('engine', '—')}",
            f"**Лот:** {primary.get('lotsize', '—')} шт.",
            f"**Валюта торгов:** {primary.get('currencyid', '—')}",
            f"**Тип цены:** {primary.get('pricetype', '—')}",
        ]
    return "\n".join(lines)


@mcp.tool(
    name="moex_get_quote",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def moex_get_quote(params: TickerInput) -> str:
    """Получить текущую котировку бумаги на MOEX (последняя цена, объём, изменение за день).

    Возвращает: последнюю цену, цену открытия, мин/макс дня,
    объём торгов, изменение в % за день, рыночную капитализацию (для акций).

    Args:
        params: TickerInput с полем ticker (str)

    Returns:
        str: Markdown-форматированная котировка
    """
    ticker = params.ticker.upper()
    # Пробуем разные движки: акции (stock/shares), облигации (bonds), фонды (ndx)
    engines_boards = [
        ("stock", "shares", "TQBR"),
        ("stock", "bonds", "TQOB"),
        ("stock", "bonds", "TQCB"),
        ("stock", "etf", "TQTF"),
    ]
    marketdata = None
    securities_row = None

    for engine, market, board in engines_boards:
        try:
            data = await _get(
                f"/engines/{engine}/markets/{market}/boards/{board}/securities/{ticker}",
                params={"iss.meta": "off"}
            )
            sec_rows = _rows(data, "securities")
            md_rows = _rows(data, "marketdata")
            if sec_rows and md_rows:
                securities_row = sec_rows[0]
                marketdata = md_rows[0]
                break
        except Exception:
            continue

    if not marketdata or not securities_row:
        return f"Котировка для {ticker} не найдена. Проверьте тикер или рынок."

    last = marketdata.get("LAST") or marketdata.get("CURRENTVALUE") or securities_row.get("PREVPRICE")
    prev = securities_row.get("PREVPRICE")
    change_pct = ""
    if last and prev and float(prev) > 0:
        chg = (float(last) - float(prev)) / float(prev) * 100
        sign = "+" if chg >= 0 else ""
        change_pct = f" ({sign}{chg:.2f}%)"

    lines = [
        f"## {ticker} — котировка",
        f"**Последняя цена:** {_fmt(last)} {securities_row.get('CURRENCYID', 'RUB')}{change_pct}",
        f"**Цена закрытия пред. дня:** {_fmt(prev)}",
        f"**Открытие:** {_fmt(marketdata.get('OPEN'))}",
        f"**Максимум дня:** {_fmt(marketdata.get('HIGH'))}",
        f"**Минимум дня:** {_fmt(marketdata.get('LOW'))}",
        f"**Объём (лоты):** {_fmt(marketdata.get('VOLTODAY'), 0)}",
        f"**Объём (руб.):** {_fmt(marketdata.get('VALTODAY'), 0)}",
        f"**Сделок сегодня:** {_fmt(marketdata.get('NUMTRADES'), 0)}",
        f"**Время обновления:** {marketdata.get('TIME', '—')}",
    ]

    cap = securities_row.get("ISSUECAPITALIZATION")
    if cap:
        cap_bn = float(cap) / 1_000_000_000
        lines.append(f"**Капитализация:** {cap_bn:,.1f} млрд руб.")

    return "\n".join(lines)


@mcp.tool(
    name="moex_get_dividends",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def moex_get_dividends(params: DividendsInput) -> str:
    """Получить историю дивидендных выплат по акции на MOEX.

    Возвращает: даты отсечек, размеры дивидендов, доходность,
    суммарные выплаты за год.

    Args:
        params: DividendsInput с полем ticker (str)

    Returns:
        str: Markdown-таблица дивидендных выплат
    """
    ticker = params.ticker.upper()
    try:
        data = await _get(f"/securities/{ticker}/dividends")
    except Exception as e:
        return f"Ошибка при запросе дивидендов: {e}"

    rows = _rows(data, "dividends")
    if not rows:
        return f"Дивиденды по {ticker} не найдены. Возможно, компания не платит дивиденды или тикер неверный."

    # Последние 10 выплат
    rows = sorted(rows, key=lambda r: r.get("registryclosedate", ""), reverse=True)[:10]

    lines = [f"## {ticker} — история дивидендов (последние {len(rows)} выплат)\n"]
    lines.append("| Дата отсечки | Дивиденд (руб.) | Доходность | Период |")
    lines.append("|---|---|---|---|")
    for r in rows:
        date = r.get("registryclosedate", "—")
        div = _fmt(r.get("value"))
        yld = _fmt(r.get("yield")) + "%" if r.get("yield") else "—"
        period = r.get("valuetype", "—")
        lines.append(f"| {date} | {div} | {yld} | {period} |")

    # Сумма за последние 12 месяцев (приблизительно)
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=365)).isoformat()
    recent = [r for r in rows if r.get("registryclosedate", "") >= cutoff]
    if recent:
        total = sum(float(r.get("value", 0) or 0) for r in recent)
        lines.append(f"\n**Суммарно за ~12 мес:** {total:.2f} руб.")

    return "\n".join(lines)


@mcp.tool(
    name="moex_search_securities",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def moex_search_securities(params: SecuritySearchInput) -> str:
    """Поиск ценных бумаг на MOEX по названию или тикеру.

    Args:
        params: SecuritySearchInput с полями query (str) и limit (int)

    Returns:
        str: Markdown-список найденных бумаг с тикерами и описанием
    """
    try:
        data = await _get("/securities", params={
            "q": params.query,
            "limit": params.limit,
            "iss.meta": "off"
        })
    except Exception as e:
        return f"Ошибка поиска: {e}"

    rows = _rows(data, "securities")
    if not rows:
        return f"Ничего не найдено по запросу «{params.query}»."

    lines = [f"## Результаты поиска: «{params.query}» ({len(rows)} бумаг)\n"]
    lines.append("| Тикер | Краткое название | Тип | Рынок |")
    lines.append("|---|---|---|---|")
    for r in rows:
        ticker = r.get("secid", "—")
        name = r.get("shortname", r.get("name", "—"))
        sec_type = r.get("type", r.get("group", "—"))
        primary_board = r.get("primary_boardid", "—")
        lines.append(f"| {ticker} | {name} | {sec_type} | {primary_board} |")

    return "\n".join(lines)


@mcp.tool(
    name="moex_get_index",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def moex_get_index(params: IndexInput) -> str:
    """Получить текущее значение и состав индекса Московской биржи.

    Поддерживаемые индексы: IMOEX (индекс МосБиржи), RTSI (РТС),
    MOEXBC (голубые фишки), MOEXOG (нефть и газ), MOEXFN (финансы) и др.

    Args:
        params: IndexInput с полем index (str, default='IMOEX')

    Returns:
        str: Текущее значение индекса и список компонентов с весами
    """
    index = params.index.upper()
    try:
        # Текущее значение
        val_data = await _get(
            f"/engines/stock/markets/index/boards/SNDX/securities/{index}",
            params={"iss.meta": "off"}
        )
        # Состав
        comp_data = await _get(f"/statistics/engines/stock/markets/index/analytics/{index}")
    except Exception as e:
        return f"Ошибка загрузки индекса {index}: {e}"

    sec_rows = _rows(val_data, "securities")
    md_rows = _rows(val_data, "marketdata")
    components = _rows(comp_data, "analytics")

    lines = [f"## Индекс {index}"]
    if sec_rows and md_rows:
        val = md_rows[0].get("CURRENTVALUE") or md_rows[0].get("LAST") or sec_rows[0].get("PREVPRICE")
        prev = sec_rows[0].get("PREVPRICE")
        lines.append(f"**Значение:** {_fmt(val)}")
        if val and prev and float(prev) > 0:
            chg = (float(val) - float(prev)) / float(prev) * 100
            sign = "+" if chg >= 0 else ""
            lines.append(f"**Изменение за день:** {sign}{chg:.2f}%")
        lines.append(f"**Время:** {md_rows[0].get('TIME', '—')}")

    if components:
        components = sorted(components, key=lambda x: float(x.get("weight", 0) or 0), reverse=True)[:20]
        lines.append(f"\n### Состав (топ-{len(components)} по весу)\n")
        lines.append("| Тикер | Вес, % |")
        lines.append("|---|---|")
        for c in components:
            lines.append(f"| {c.get('secid', '—')} | {_fmt(c.get('weight'))} |")

    return "\n".join(lines)


@mcp.tool(
    name="moex_get_bond_info",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def moex_get_bond_info(params: ObligationInput) -> str:
    """Получить детальную информацию по облигации или ОФЗ на MOEX.

    Возвращает: купонную ставку, дату погашения, НКД, доходность к погашению (YTM),
    дюрацию, номинал, текущую цену.

    Args:
        params: ObligationInput с полем ticker (str)

    Returns:
        str: Markdown-карточка облигации с ключевыми показателями
    """
    ticker = params.ticker.upper()

    # Пробуем несколько досок для облигаций
    boards = [("stock", "bonds", "TQOB"), ("stock", "bonds", "TQCB"), ("stock", "bonds", "TQOD")]
    sec_row = None
    md_row = None
    for engine, market, board in boards:
        try:
            data = await _get(
                f"/engines/{engine}/markets/{market}/boards/{board}/securities/{ticker}",
                params={"iss.meta": "off"}
            )
            s = _rows(data, "securities")
            m = _rows(data, "marketdata")
            if s:
                sec_row = s[0]
                md_row = m[0] if m else {}
                break
        except Exception:
            continue

    if not sec_row:
        # Пробуем базовую информацию
        try:
            info_data = await _get(f"/securities/{ticker}")
            desc = _rows(info_data, "description")
            info = {r["name"]: r["value"] for r in desc}
            if not info:
                return f"Облигация {ticker} не найдена на MOEX."
            return (
                f"## {ticker} — {info.get('NAME', '—')}\n"
                f"**ISIN:** {info.get('ISIN', '—')}\n"
                f"**Номинал:** {_fmt(info.get('FACEVALUE'))} {info.get('FACEUNIT', 'RUB')}\n"
                f"**Дата погашения:** {info.get('MATDATE', '—')}\n"
                f"**Ставка купона:** {info.get('COUPONPERCENT', '—')}%\n"
                f"**Частота купонов:** {info.get('COUPONFREQUENCY', '—')} в год\n"
                f"**Эмитент:** {info.get('ISSUERNAME', '—')}\n"
                f"> Торговые данные (цена, YTM) недоступны — возможно, бумага не торгуется."
            )
        except Exception as e:
            return f"Ошибка: {e}"

    last_price = md_row.get("LAST") or sec_row.get("PREVPRICE")
    nominal = sec_row.get("FACEVALUE", 1000)
    price_rub = ""
    if last_price and nominal:
        try:
            price_rub = f" = {float(last_price) / 100 * float(nominal):,.2f} руб."
        except Exception:
            pass

    lines = [
        f"## {ticker} — {sec_row.get('SHORTNAME', '—')}",
        f"**ISIN:** {sec_row.get('ISIN', '—')}",
        f"**Номинал:** {_fmt(nominal)} руб.",
        f"**Текущая цена:** {_fmt(last_price)}%{price_rub}",
        f"**НКД:** {_fmt(sec_row.get('ACCRUEDINT'))} руб.",
        f"**Дата погашения:** {sec_row.get('MATDATE', '—')}",
        f"**Дюрация:** {_fmt(sec_row.get('DURATION'))} дней",
        f"**Доходность к погашению (YTM):** {_fmt(sec_row.get('YIELDATPREVWAPRICE'))}%",
        f"**Ставка купона:** {_fmt(sec_row.get('COUPONPERCENT'))}%",
        f"**Размер купона:** {_fmt(sec_row.get('COUPONVALUE'))} руб.",
        f"**Следующий купон:** {sec_row.get('NEXTCOUPON', '—')}",
        f"**Объём торгов (руб.):** {_fmt(md_row.get('VALTODAY'), 0)}",
    ]
    return "\n".join(lines)


@mcp.tool(
    name="moex_get_market_overview",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def moex_get_market_overview() -> str:
    """Получить обзор рынка MOEX: ключевые индексы, курсы валют, лидеры роста и падения.

    Не требует параметров. Возвращает: значения IMOEX и RTSI,
    курс USD/RUB и EUR/RUB, топ-5 акций по росту и падению за день.

    Returns:
        str: Markdown-дашборд состояния рынка
    """
    lines = ["## Обзор рынка MOEX\n"]

    # Индексы
    for idx in ["IMOEX", "RTSI"]:
        try:
            data = await _get(
                f"/engines/stock/markets/index/boards/SNDX/securities/{idx}",
                params={"iss.meta": "off"}
            )
            s = _rows(data, "securities")
            m = _rows(data, "marketdata")
            if s and m:
                val = m[0].get("CURRENTVALUE") or m[0].get("LAST") or s[0].get("PREVPRICE")
                prev = s[0].get("PREVPRICE")
                chg = ""
                if val and prev and float(prev) > 0:
                    c = (float(val) - float(prev)) / float(prev) * 100
                    chg = f" ({'+' if c >= 0 else ''}{c:.2f}%)"
                lines.append(f"**{idx}:** {_fmt(val)}{chg}")
        except Exception:
            lines.append(f"**{idx}:** недоступен")

    # Валюты
    lines.append("")
    for pair in ["USD000UTSTOM", "EUR_RUB__TOM"]:
        try:
            data = await _get(
                f"/engines/currency/markets/selt/boards/CETS/securities/{pair}",
                params={"iss.meta": "off"}
            )
            m = _rows(data, "marketdata")
            if m:
                rate = m[0].get("LAST") or m[0].get("CURRENTVALUE")
                label = "USD/RUB" if "USD" in pair else "EUR/RUB"
                lines.append(f"**{label}:** {_fmt(rate)}")
        except Exception:
            pass

    # Топ акций по объёму из IMOEX
    try:
        data = await _get(
            "/engines/stock/markets/shares/boards/TQBR/securities",
            params={"iss.meta": "off", "iss.only": "marketdata,securities"}
        )
        sec = {r["SECID"]: r for r in _rows(data, "securities")}
        md = _rows(data, "marketdata")

        movers = []
        for r in md:
            tid = r.get("SECID", "")
            last = r.get("LAST")
            prev = sec.get(tid, {}).get("PREVPRICE")
            vol = r.get("VALTODAY")
            if last and prev and float(prev) > 0 and vol and float(vol) > 0:
                chg = (float(last) - float(prev)) / float(prev) * 100
                movers.append({"ticker": tid, "chg": chg, "last": last, "vol": vol})

        if movers:
            movers.sort(key=lambda x: x["chg"], reverse=True)
            lines.append("\n### Топ-5 роста")
            for m in movers[:5]:
                lines.append(f"- **{m['ticker']}** {_fmt(m['last'])} руб. (+{m['chg']:.2f}%)")
            lines.append("\n### Топ-5 падения")
            for m in movers[-5:][::-1]:
                lines.append(f"- **{m['ticker']}** {_fmt(m['last'])} руб. ({m['chg']:.2f}%)")
    except Exception:
        lines.append("\n_Данные по акциям временно недоступны._")

    return "\n".join(lines)


@mcp.tool(
    name="moex_full_analysis",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
)
async def moex_full_analysis(params: TickerInput) -> str:
    """Полный анализ акции по инвестиционному чеклисту: котировка, дивиденды, мультипликаторы, риски.

    Собирает данные из нескольких эндпоинтов MOEX и формирует
    структурированный инвестиционный отчёт.

    Args:
        params: TickerInput с полем ticker (str)

    Returns:
        str: Полный Markdown-отчёт по бумаге
    """
    ticker = params.ticker.upper()
    sections = []

    # 1. Базовая информация
    try:
        info_data = await _get(f"/securities/{ticker}")
        desc = _rows(info_data, "description")
        info = {r["name"]: r["value"] for r in desc}
        boards = _rows(info_data, "boards")
        primary = next((b for b in boards if b.get("is_primary") == 1), boards[0] if boards else {})

        sections.append(
            f"## {ticker} — {info.get('NAME', info.get('SHORTNAME', '—'))}\n"
            f"**ISIN:** {info.get('ISIN', '—')} | "
            f"**Тип:** {info.get('TYPE', '—')} | "
            f"**Лот:** {primary.get('lotsize', '—')} шт. | "
            f"**Статус:** {info.get('STATUS', '—')}"
        )
    except Exception as e:
        sections.append(f"## {ticker}\n_Базовая информация недоступна: {e}_")

    # 2. Котировка
    try:
        for engine, market, board in [
            ("stock", "shares", "TQBR"),
            ("stock", "etf", "TQTF"),
        ]:
            try:
                data = await _get(
                    f"/engines/{engine}/markets/{market}/boards/{board}/securities/{ticker}",
                    params={"iss.meta": "off"}
                )
                s = _rows(data, "securities")
                m = _rows(data, "marketdata")
                if s and m:
                    sec_row, md_row = s[0], m[0]
                    last = md_row.get("LAST") or sec_row.get("PREVPRICE")
                    prev = sec_row.get("PREVPRICE")
                    chg = ""
                    if last and prev and float(prev) > 0:
                        c = (float(last) - float(prev)) / float(prev) * 100
                        chg = f" ({'+' if c >= 0 else ''}{c:.2f}%)"
                    cap = sec_row.get("ISSUECAPITALIZATION")
                    cap_str = ""
                    if cap:
                        cap_str = f"\n**Капитализация:** {float(cap)/1e9:,.1f} млрд руб."

                    sections.append(
                        f"\n### Котировка\n"
                        f"**Цена:** {_fmt(last)} руб.{chg}\n"
                        f"**Открытие:** {_fmt(md_row.get('OPEN'))} | "
                        f"**Макс:** {_fmt(md_row.get('HIGH'))} | "
                        f"**Мин:** {_fmt(md_row.get('LOW'))}\n"
                        f"**Объём:** {_fmt(md_row.get('VALTODAY'), 0)} руб.{cap_str}"
                    )
                    break
            except Exception:
                continue
    except Exception:
        pass

    # 3. Дивиденды
    try:
        div_data = await _get(f"/securities/{ticker}/dividends")
        div_rows = _rows(div_data, "dividends")
        if div_rows:
            div_rows_sorted = sorted(div_rows, key=lambda r: r.get("registryclosedate", ""), reverse=True)
            recent = div_rows_sorted[:5]
            div_section = "\n### Дивиденды (последние 5 выплат)\n"
            div_section += "| Дата отсечки | Дивиденд (руб.) | Доходность |\n|---|---|---|\n"
            for r in recent:
                yld = f"{_fmt(r.get('yield'))}%" if r.get("yield") else "—"
                div_section += f"| {r.get('registryclosedate','—')} | {_fmt(r.get('value'))} | {yld} |\n"

            from datetime import date, timedelta
            cutoff = (date.today() - timedelta(days=365)).isoformat()
            ttm = [r for r in div_rows if r.get("registryclosedate", "") >= cutoff]
            if ttm:
                ttm_total = sum(float(r.get("value", 0) or 0) for r in ttm)
                div_section += f"\n**Дивиденды за 12 мес:** {ttm_total:.2f} руб."
            sections.append(div_section)
        else:
            sections.append("\n### Дивиденды\n_Дивидендных выплат не найдено._")
    except Exception:
        sections.append("\n### Дивиденды\n_Данные недоступны._")

    # 4. Итоговый чеклист
    sections.append(
        "\n### Чеклист для решения\n"
        "| Критерий | Нужно проверить |\n|---|---|\n"
        "| P/E vs сектор | conomy.ru / smart-lab.ru |\n"
        "| Net Debt/EBITDA | Последний отчёт МСФО |\n"
        "| FCF положительный | Отчёт о движении ДС |\n"
        "| Дивдоходность > 9% | См. выше |\n"
        "| MA200 (техника) | tradingview.com |\n"
        "| Новости / риски | smart-lab.ru/news |\n"
    )

    return "\n".join(sections)


if __name__ == "__main__":
    mcp.run()
