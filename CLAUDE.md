# CLAUDE.md - FattureInCloud MCP Server

Server MCP (Model Context Protocol) per integrazione con Fatture in Cloud API.
Fornisce 20 tools organizzati in 7 categorie per gestione fatturazione, pagamenti e analisi.

---

## Architettura

```
fattureincloud-mcp-server/
├── server.py              # Entry point, registra tutti i tools
├── src/
│   ├── config.py          # Configurazione API (OAuth2)
│   ├── utils.py           # Funzioni condivise (get_payment_info)
│   └── tools/
│       ├── invoices.py    # Fatture emesse (2 tools)
│       ├── payments.py    # Pagamenti e scadenze (2 tools)
│       ├── clients.py     # Gestione clienti (2 tools)
│       ├── expenses.py    # Fatture ricevute/spese (4 tools)
│       ├── analytics.py   # Statistiche e report (4 tools)
│       ├── info.py        # Info azienda (1 tool)
│       └── reminders.py   # Solleciti e aging (5 tools) - NUOVO
├── Dockerfile             # Container Docker per deploy
├── requirements.txt       # Dipendenze Python
└── .env                   # Credenziali API (NON committare)
```

---

## Tools Disponibili (20 totali)

| Categoria | Tool | Descrizione |
|-----------|------|-------------|
| **invoices** | `get_invoices` | Lista fatture emesse con filtri (date, cliente, stato) |
| | `get_invoice` | Dettaglio completo singola fattura |
| **payments** | `get_overdue_invoices` | Fatture scadute non pagate (SENZA netting) |
| | `get_payment_summary` | Riepilogo aggregato pagamenti e scadenze |
| **clients** | `get_clients` | Lista clienti con filtro nome |
| | `get_client_invoices` | Tutte le fatture per cliente specifico |
| **expenses** | `get_received_invoices` | Fatture ricevute da fornitori |
| | `get_received_invoice` | Dettaglio fattura ricevuta |
| | `get_unpaid_received_invoices` | Fatture da pagare ai fornitori |
| | `get_expenses_by_month` | Spese mensili aggregate |
| **analytics** | `get_revenue_by_month` | Fatturato mensile per anno |
| | `get_revenue_by_client` | Fatturato per cliente (top N) |
| | `get_yearly_stats` | Statistiche annuali complete |
| **info** | `get_company_info` | Informazioni azienda |
| **reminders** | `get_overdue_invoices_with_netting` | Fatture scadute CON netting NC automatico FIFO |
| | `get_aging_report` | Aging crediti (1-30, 31-60, 61-90, 90+ gg) |
| | `get_reminder_data` | Dati strutturati per solleciti (anagrafica + fatture) |
| | `get_client_payment_behavior` | Analisi DSO, % ritardi, trend, rating cliente |
| | `get_reminder_priority_queue` | Coda priorita solleciti ordinata per urgenza |

---

## Netting Note di Credito (FIFO)

### Logica Implementata (2026-02-07)

Il tool `get_overdue_invoices_with_netting` applica automaticamente il netting tra fatture e note di credito:

1. **Raggruppa per cliente**: NC e fatture sono raggruppate per nome cliente (case-insensitive)
2. **Ordina FIFO**: Fatture ordinate per data emissione (piu vecchie prima)
3. **Somma NC**: Totale NC per cliente calcolato su `amount_net` (imponibile)
4. **Applica credito**:
   - Se NC >= fattura → fattura completamente coperta (esclusa)
   - Se NC copre parzialmente → aggiorna remaining
5. **Tolleranza**: 0.01 EUR per arrotondamenti floating point

### Funzione Core

```python
# src/tools/reminders.py
def _apply_netting_fifo(overdue_items, credit_notes) -> tuple[list, list, dict]:
    """
    Returns:
        - fatture_con_saldo_aggiornato: fatture ancora da incassare
        - dettagli_netting: log di quali fatture sono state compensate
        - nc_per_cliente: dizionario NC raggruppate per cliente
    """
```

### Esempio Output

```
FATTURE SCADUTE (con netting NC automatico FIFO)
================================================
Fatture scadute: 7
Totale da incassare: 14,364.20 EUR

NETTING APPLICATO (FIFO per cliente)
Totale compensato: 41,162.26 EUR

FATTURE COMPLETAMENTE COPERTE: 5
  - Fattura 1/g (EGLUE S.R.L.)
    Emissione: 2025-01-07 | Scadenza: 2025-01-07
    Importo: 9,571.00 EUR → ESCLUSA
    Compensata con NC:
      • NC 2 del 2025-01-31 - 9,571.00 EUR
```

---

## Workflow Solleciti Consigliato

```
┌─────────────────────────────────────────────────────────────┐
│  1. get_overdue_invoices_with_netting                       │
│     → Fatture scadute pulite (escluse NC)                   │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│  2. get_aging_report                                        │
│     → Situazione per fascia (1-30, 31-60, 61-90, 90+ gg)    │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│  3. get_reminder_priority_queue                             │
│     → Classifica clienti da sollecitare per urgenza         │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│  4. get_reminder_data (per cliente)                         │
│     → Anagrafica + fatture + contatti per sollecito         │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│  5. get_client_payment_behavior (opzionale)                 │
│     → DSO, trend, rating per calibrare tono sollecito       │
└─────────────────────────────────────────────────────────────┘
```

### Priority Score

Il tool `get_reminder_priority_queue` calcola uno score basato su:
- **Importo** x **log(giorni ritardo)** x **sqrt(numero fatture)**
- Urgency level: CRITICO (90+ gg), ALTO (60-90), MEDIO (30-60), BASSO (<30)

---

## Configurazione

### Variabili Ambiente (.env)

```bash
# OAuth2 - Fatture in Cloud API
FATTUREINCLOUD_ACCESS_TOKEN=<token>
FATTUREINCLOUD_REFRESH_TOKEN=<token>
FATTUREINCLOUD_CLIENT_ID=<client_id>
FATTUREINCLOUD_CLIENT_SECRET=<secret>
FATTUREINCLOUD_COMPANY_ID=<company_id>
```

### Generare Token OAuth2

```bash
python auth_setup.py
# Apre browser per autorizzazione → salva token in .env
```

---

## Esecuzione

### Locale (stdio)

```bash
# Attiva venv
source venv/bin/activate

# Avvia server stdio (per Claude Code/Desktop)
python server.py
```

### Docker (HTTP/SSE)

```bash
# Build immagine
docker build -t fattureincloud-mcp .

# Run container (passa env vars)
docker run -d \
  --name fattureincloud-mcp \
  -p 3002:3002 \
  -e FATTUREINCLOUD_ACCESS_TOKEN=xxx \
  -e FATTUREINCLOUD_REFRESH_TOKEN=xxx \
  -e FATTUREINCLOUD_CLIENT_ID=xxx \
  -e FATTUREINCLOUD_CLIENT_SECRET=xxx \
  -e FATTUREINCLOUD_COMPANY_ID=xxx \
  fattureincloud-mcp python server.py --http

# Verifica log
docker logs -f fattureincloud-mcp
```

### Rebuild Dopo Modifiche

```bash
docker stop fattureincloud-mcp && docker rm fattureincloud-mcp
docker build -t fattureincloud-mcp .
docker run -d --name fattureincloud-mcp -p 3002:3002 --env-file .env fattureincloud-mcp python server.py --http
```

---

## Integrazione Claude Code

### Profilo MCP

Nel file `~/.claude.json` o profilo `AMMI`:

```json
{
  "mcpServers": {
    "fattureincloud": {
      "command": "python",
      "args": ["/path/to/fattureincloud-mcp-server/server.py"],
      "env": {
        "FATTUREINCLOUD_ACCESS_TOKEN": "xxx"
      }
    }
  }
}
```

### Avvio con Profilo

```bash
claude --profile AMMI
```

---

## File Chiave

| File | Righe | Descrizione |
|------|-------|-------------|
| `server.py:46-70` | | Registrazione tools e handlers |
| `src/tools/reminders.py:53-144` | | Funzione `_apply_netting_fifo` |
| `src/tools/reminders.py:147-263` | | Handler `get_overdue_invoices_with_netting` |
| `src/utils.py:6-51` | | Funzione `get_payment_info` |
| `src/config.py` | | Configurazione OAuth2 API |

---

## Dipendenze

```
fattureincloud-python-sdk==2.1.3   # SDK ufficiale FattureInCloud
mcp                                 # MCP SDK Anthropic
python-dotenv==1.0.1               # Variabili ambiente
uvicorn>=0.27.0                    # Server HTTP (mode SSE)
starlette>=0.36.0                  # Framework web (mode SSE)
```

---

## Changelog

### 2026-02-07
- Aggiunto modulo `reminders.py` con 5 nuovi tools per gestione solleciti
- Implementato netting FIFO automatico per note di credito
- Aging report con fasce temporali standard
- Priority queue per solleciti basata su score

### 2026-01-14
- Implementata paginazione API per gestire grandi volumi dati
- Aggiornato SDK a versione 2.1.3

---

**Progetto**: FattureInCloud MCP Server
**Maintainer**: Massimo Mostallino <massimo.mostallino@hestro.it>
**Ultimo aggiornamento**: 7 Febbraio 2026
