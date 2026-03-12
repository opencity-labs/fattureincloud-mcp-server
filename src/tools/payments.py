"""
Tools per gestione pagamenti e scadenze.
"""

from datetime import datetime, timedelta
from mcp.types import Tool, TextContent
from fattureincloud_python_sdk.api import issued_documents_api

from ..config import COMPANY_ID, get_api_client
from ..utils import get_payment_info


def _get_full_invoice_number(inv) -> str:
    """
    Restituisce il numero fattura completo con numerazione.
    Es: "19" + "/g" = "19/g"
    """
    number = str(inv.number) if inv.number else "N/A"
    if inv.numeration:
        return f"{number}{inv.numeration}"
    return number


async def handle_get_overdue_invoices(arguments: dict) -> list[TextContent]:
    """Fatture scadute non pagate."""
    limit = arguments.get("limit", 50)

    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        try:
            # Cerca fatture fino a oggi (ultimi 5 anni per includere storiche non pagate)
            # FIX 2026-02-07: aumentato da 365 a 1825 giorni per catturare fatture vecchie
            to_date = datetime.now().strftime("%Y-%m-%d")
            from_date = (datetime.now() - timedelta(days=1825)).strftime("%Y-%m-%d")

            q = f"date >= '{from_date}' and date <= '{to_date}'"

            # Recupera TUTTI i tipi di documento facendo chiamate separate
            invoices = []

            doc_types = ["invoice", "credit_note", "receipt", "order", "quote",
                        "proforma", "delivery_note", "work_report", "supplier_order", "self_invoice"]

            for doc_type in doc_types:
                page = 1
                while True:
                    try:
                        response = api.list_issued_documents(
                            company_id=COMPANY_ID,
                            type=doc_type,
                            q=q,
                            page=page,
                            per_page=100,
                            fieldset="detailed"
                        )

                        if response.data:
                            invoices.extend(response.data)

                        # Verifica se ci sono altre pagine
                        if page >= response.last_page:
                            break

                        page += 1
                    except Exception as e:
                        # Se il tipo non esiste o non è supportato, continua
                        if "404" in str(e) or "not found" in str(e).lower():
                            break
                        raise

            overdue = []

            today = datetime.now().date()

            for inv in invoices:
                pay_info = get_payment_info(inv)

                # Controlla se scaduta e non pagata
                if pay_info["due_date"] and pay_info["remaining"] > 0:
                    due_date = datetime.strptime(pay_info["due_date"], "%Y-%m-%d").date()
                    if due_date < today:
                        days_overdue = (today - due_date).days
                        overdue.append({
                            "numero": _get_full_invoice_number(inv),
                            "data": str(inv.var_date) if inv.var_date else None,
                            "scadenza": pay_info["due_date"],
                            "giorni_ritardo": days_overdue,
                            "cliente": inv.entity.name if inv.entity else "N/A",
                            "importo": pay_info["total"],
                            "da_pagare": pay_info["remaining"],
                        })

            # Ordina per giorni di ritardo decrescenti
            overdue.sort(key=lambda x: x["giorni_ritardo"], reverse=True)
            overdue = overdue[:limit]

            if not overdue:
                output = "Nessuna fattura scaduta trovata."
            else:
                total_overdue = sum(f["da_pagare"] for f in overdue)
                output = f"Trovate {len(overdue)} fatture scadute (totale: {total_overdue:.2f} EUR):\n\n"

                for f in overdue:
                    output += f"- N. {f['numero']} | {f['cliente']}\n"
                    output += f"  Data fattura: {f['data']}\n"
                    output += f"  Scadenza: {f['scadenza']} ({f['giorni_ritardo']} giorni fa)\n"
                    output += f"  Importo totale: {f['importo']:.2f} EUR\n"
                    output += f"  Da incassare: {f['da_pagare']:.2f} EUR\n\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


async def handle_get_payment_summary(arguments: dict) -> list[TextContent]:
    """Riepilogo pagamenti aggregato."""
    from_date = arguments.get("from_date")
    to_date = arguments.get("to_date")

    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        try:
            if not to_date:
                to_date = datetime.now().strftime("%Y-%m-%d")
            if not from_date:
                from_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

            q = f"date >= '{from_date}' and date <= '{to_date}'"

            # Loop paginazione per recuperare TUTTE le fatture
            # FIX 2026-03-05: iterare sui tipi di documento (type="" non accettato dall'API)
            invoices = []
            doc_types = ["invoice", "credit_note", "receipt", "proforma"]

            for doc_type in doc_types:
                page = 1
                while True:
                    try:
                        response = api.list_issued_documents(
                            company_id=COMPANY_ID,
                            type=doc_type,
                            q=q,
                            page=page,
                            per_page=100,
                            fieldset="detailed"
                        )

                        if response.data:
                            invoices.extend(response.data)

                        if page >= response.last_page:
                            break

                        page += 1
                    except Exception:
                        break

            # Contatori
            total_invoices = 0
            total_amount = 0.0
            total_paid = 0.0
            total_remaining = 0.0

            paid_count = 0
            partially_paid_count = 0
            not_paid_count = 0
            overdue_count = 0
            overdue_amount = 0.0

            today = datetime.now().date()

            for inv in invoices:
                pay_info = get_payment_info(inv)

                total_invoices += 1
                total_amount += pay_info["total"]
                total_paid += pay_info["paid"]
                total_remaining += pay_info["remaining"]

                if pay_info["status"] == "paid":
                    paid_count += 1
                elif pay_info["status"] == "partially_paid":
                    partially_paid_count += 1
                else:
                    not_paid_count += 1

                # Controlla scaduti
                if pay_info["due_date"] and pay_info["remaining"] > 0:
                    due_date = datetime.strptime(pay_info["due_date"], "%Y-%m-%d").date()
                    if due_date < today:
                        overdue_count += 1
                        overdue_amount += pay_info["remaining"]

            output = f"""
RIEPILOGO PAGAMENTI
{'=' * 40}
Periodo: {from_date} - {to_date}

FATTURE:
- Totale fatture: {total_invoices}
- Importo totale: {total_amount:.2f} EUR

STATO PAGAMENTI:
- Pagate: {paid_count} ({total_paid:.2f} EUR)
- Parzialmente pagate: {partially_paid_count}
- Non pagate: {not_paid_count}
- Da incassare: {total_remaining:.2f} EUR

SCADUTI:
- Fatture scadute: {overdue_count}
- Importo scaduto: {overdue_amount:.2f} EUR

PERCENTUALI:
- % Pagate: {(paid_count / total_invoices * 100) if total_invoices > 0 else 0:.1f}%
- % Incassato: {(total_paid / total_amount * 100) if total_amount > 0 else 0:.1f}%
"""

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


def get_payment_tools():
    """Restituisce la lista di tool per pagamenti."""
    return [
        Tool(
            name="get_overdue_invoices",
            description="Fatture scadute non pagate",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Numero massimo risultati, default: 50"
                    }
                }
            }
        ),
        Tool(
            name="get_payment_summary",
            description="Riepilogo aggregato pagamenti e scadenze per periodo",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_date": {
                        "type": "string",
                        "description": "Data inizio (YYYY-MM-DD), default: ultimi 90 giorni"
                    },
                    "to_date": {
                        "type": "string",
                        "description": "Data fine (YYYY-MM-DD), default: oggi"
                    }
                }
            }
        ),
    ]


def get_payment_handlers():
    """Restituisce il dizionario di handler per pagamenti."""
    return {
        "get_overdue_invoices": handle_get_overdue_invoices,
        "get_payment_summary": handle_get_payment_summary,
    }
