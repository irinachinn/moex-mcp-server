# 📈 MOEX MCP Server

> Connect Claude AI to Moscow Exchange real-time data via MCP protocol

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![MCP](https://img.shields.io/badge/MCP-1.27-green)
![MOEX ISS API](https://img.shields.io/badge/MOEX_ISS-API-orange)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

## What is this?

This MCP (Model Context Protocol) server connects **Claude AI** directly to the **Moscow Exchange (MOEX)** public ISS API — giving Claude the ability to fetch real-time stock quotes, dividend history, bond details, and market overviews without any manual data entry.

Built for long-term investors who want AI-powered analysis of Russian equities and bonds.

---

## Features

| Tool | Description |
|---|---|
| `moex_get_quote` | Real-time price, volume, daily change |
| `moex_get_security_info` | ISIN, lot size, listing date, status |
| `moex_get_dividends` | Full dividend history with yields and ex-dates |
| `moex_get_bond_info` | Coupon rate, YTM, duration, NKD, maturity |
| `moex_get_index` | Index value + top components by weight |
| `moex_get_market_overview` | IMOEX, RTSI, USD/RUB, top movers |
| `moex_search_securities` | Search any ticker or company name |
| `moex_full_analysis` | Full investment checklist report for a stock |

---

## Quick Start

### 1. Requirements
- Python 3.11+
- Claude Desktop app

### 2. Install dependencies

```bash
pip3.11 install "mcp[cli]" httpx pydantic
```

### 3. Add to Claude Desktop config

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "moex": {
      "command": "/opt/homebrew/bin/python3.11",
      "args": ["/path/to/moex_mcp.py"]
    }
  }
}
```

### 4. Restart Claude Desktop

That's it. Now ask Claude anything about Russian stocks:

> *"Full analysis of SBER"*
> *"Show dividends for LKOH"*
> *"What's the current IMOEX value?"*
> *"Bond details for SU26238RMFS3"*

---

## How it works

```
Claude Desktop
     │
     │ MCP Protocol
     ▼
moex_mcp.py  ──── HTTPS ────▶  iss.moex.com  (free, no auth)
     │
     ▼
Real-time data: quotes, dividends, bonds, indices
```

The server uses the **MOEX ISS REST API** — fully public, no registration or API key required. Data is delayed ~15 minutes on the free tier.

---

## Example Output

```
## LKOH — НК ЛУКОЙЛ
Price: 4,911.00 RUB (+0.56%)
Open: 4,883.50 | High: 4,911.00 | Low: 4,879.00
Volume: 189,905,384 RUB

Dividends (last 5):
| Ex-date    | Amount  | Yield |
| 2025-06-03 | 541 RUB |  11%  |
| 2024-12-17 | 514 RUB |  10%  |
```

---

## Tech Stack

- **Python 3.11** — core language
- **FastMCP** — MCP server framework by Anthropic
- **httpx** — async HTTP client
- **pydantic** — data validation
- **MOEX ISS API** — `https://iss.moex.com/iss`

---

## License

MIT — free to use, modify and distribute.
