"""
Tools per analytics e statistiche.
"""

from datetime import datetime, timedelta
from collections import defaultdict
from mcp.types import Tool, TextContent
from fattureincloud_python_sdk.api import issued_documents_api

from ..config import COMPANY_ID, get_api_client


async def handle_get_revenue_by_month(arguments: dict) -> list[TextContent]:
    """Fatturato mensile."""
    year = arguments.get("year")
    months = arguments.get("months", 12)

    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        try:
            if not year:
                year = datetime.now().year

            from_date = f"{year}-01-01"
            to_date = f"{year}-12-31"

            q = f"date >= '{from_date}' and date <= '{to_date}'"

            # Loop paginazione per recuperare TUTTE le fatture
            invoices = []
            page = 1

            while True:
                response = api.list_issued_documents(
                    company_id=COMPANY_ID,
                    type="invoice",
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

            # Aggrega per mese
            monthly_revenue = defaultdict(float)
            monthly_counts = defaultdict(int)

            for inv in invoices:
                if inv.var_date:
                    month = inv.var_date.strftime("%Y-%m")
                    monthly_revenue[month] += inv.amount_gross or 0
                    monthly_counts[month] += 1

            if not monthly_revenue:
                output = f"Nessun fatturato trovato per l'anno {year}."
            else:
                sorted_months = sorted(monthly_revenue.keys())
                if len(sorted_months) > months:
                    sorted_months = sorted_months[-months:]

                total_year = sum(monthly_revenue[m] for m in sorted_months)

                output = f"FATTURATO MENSILE - Anno {year}\n"
                output += f"{'=' * 40}\n\n"

                for month in sorted_months:
                    month_name = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
                    output += f"{month_name}:\n"
                    output += f"  Fatture: {monthly_counts[month]}\n"
                    output += f"  Fatturato: {monthly_revenue[month]:.2f} EUR\n\n"

                output += f"TOTALE ANNO: {total_year:.2f} EUR\n"
                output += f"MEDIA MENSILE: {total_year / len(sorted_months):.2f} EUR\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


async def handle_get_revenue_by_client(arguments: dict) -> list[TextContent]:
    """Fatturato per cliente."""
    from_date = arguments.get("from_date")
    to_date = arguments.get("to_date")
    limit = arguments.get("limit", 20)

    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        try:
            if not to_date:
                to_date = datetime.now().strftime("%Y-%m-%d")
            if not from_date:
                from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

            q = f"date >= '{from_date}' and date <= '{to_date}'"

            # Loop paginazione per recuperare TUTTE le fatture
            invoices = []
            page = 1

            while True:
                response = api.list_issued_documents(
                    company_id=COMPANY_ID,
                    type="invoice",
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

            # Aggrega per cliente
            client_revenue = defaultdict(float)
            client_counts = defaultdict(int)

            for inv in invoices:
                if inv.entity and inv.entity.name:
                    client_name = inv.entity.name
                    client_revenue[client_name] += inv.amount_gross or 0
                    client_counts[client_name] += 1

            if not client_revenue:
                output = "Nessun fatturato trovato."
            else:
                # Ordina per fatturato decrescente
                sorted_clients = sorted(client_revenue.items(), key=lambda x: x[1], reverse=True)
                sorted_clients = sorted_clients[:limit]

                total_revenue = sum(client_revenue.values())

                output = f"FATTURATO PER CLIENTE\n"
                output += f"{'=' * 40}\n"
                output += f"Periodo: {from_date} - {to_date}\n\n"

                for i, (client_name, revenue) in enumerate(sorted_clients, 1):
                    percentage = (revenue / total_revenue * 100) if total_revenue > 0 else 0
                    output += f"{i}. {client_name}\n"
                    output += f"   Fatture: {client_counts[client_name]}\n"
                    output += f"   Fatturato: {revenue:.2f} EUR ({percentage:.1f}%)\n\n"

                output += f"TOTALE: {total_revenue:.2f} EUR\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


async def handle_get_yearly_stats(arguments: dict) -> list[TextContent]:
    """Statistiche annuali complete."""
    year = arguments.get("year")

    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        try:
            if not year:
                year = datetime.now().year

            from_date = f"{year}-01-01"
            to_date = f"{year}-12-31"

            q = f"date >= '{from_date}' and date <= '{to_date}'"

            # Loop paginazione per recuperare TUTTE le fatture
            invoices = []
            page = 1

            while True:
                response = api.list_issued_documents(
                    company_id=COMPANY_ID,
                    type="invoice",
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

            if not invoices:
                return [TextContent(type="text", text=f"Nessuna fattura trovata per l'anno {year}.")]

            # Contatori
            total_invoices = len(invoices)
            total_revenue = sum(inv.amount_gross or 0 for inv in invoices)
            total_net = sum(inv.amount_net or 0 for inv in invoices)
            total_vat = sum(inv.amount_vat or 0 for inv in invoices)

            # Clienti unici
            unique_clients = len(set(inv.entity.name for inv in invoices if inv.entity and inv.entity.name))

            # Cliente top
            client_revenue = defaultdict(float)
            for inv in invoices:
                if inv.entity and inv.entity.name:
                    client_revenue[inv.entity.name] += inv.amount_gross or 0

            top_client = max(client_revenue.items(), key=lambda x: x[1]) if client_revenue else ("N/A", 0)

            # Fatturato per trimestre
            q1 = sum(inv.amount_gross or 0 for inv in invoices if inv.var_date and inv.var_date.month in [1, 2, 3])
            q2 = sum(inv.amount_gross or 0 for inv in invoices if inv.var_date and inv.var_date.month in [4, 5, 6])
            q3 = sum(inv.amount_gross or 0 for inv in invoices if inv.var_date and inv.var_date.month in [7, 8, 9])
            q4 = sum(inv.amount_gross or 0 for inv in invoices if inv.var_date and inv.var_date.month in [10, 11, 12])

            output = f"""
STATISTICHE ANNUALI - {year}
{'=' * 40}

FATTURATO:
- Totale fatture: {total_invoices}
- Fatturato lordo: {total_revenue:.2f} EUR
- Imponibile: {total_net:.2f} EUR
- IVA: {total_vat:.2f} EUR

CLIENTI:
- Clienti attivi: {unique_clients}
- Cliente top: {top_client[0]} ({top_client[1]:.2f} EUR)

MEDIE:
- Fattura media: {total_revenue / total_invoices:.2f} EUR
- Fatturato medio/cliente: {total_revenue / unique_clients:.2f} EUR
- Fatturato medio/mese: {total_revenue / 12:.2f} EUR

TRIMESTRI:
- Q1 (Gen-Mar): {q1:.2f} EUR
- Q2 (Apr-Giu): {q2:.2f} EUR
- Q3 (Lug-Set): {q3:.2f} EUR
- Q4 (Ott-Dic): {q4:.2f} EUR
"""

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


def get_analytics_tools():
    """Restituisce la lista di tool per analytics."""
    return [
        Tool(
            name="get_revenue_by_month",
            description="Fatturato mensile aggregato per anno",
            inputSchema={
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "Anno di riferimento, default: anno corrente"
                    },
                    "months": {
                        "type": "integer",
                        "description": "Numero di mesi da mostrare (ultimi N), default: 12"
                    }
                }
            }
        ),
        Tool(
            name="get_revenue_by_client",
            description="Fatturato per cliente ordinato per importo",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_date": {
                        "type": "string",
                        "description": "Data inizio (YYYY-MM-DD), default: ultimo anno"
                    },
                    "to_date": {
                        "type": "string",
                        "description": "Data fine (YYYY-MM-DD), default: oggi"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Numero clienti da mostrare, default: 20"
                    }
                }
            }
        ),
        Tool(
            name="get_yearly_stats",
            description="Statistiche annuali complete (fatturato, clienti, medie, trimestri)",
            inputSchema={
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "Anno di riferimento, default: anno corrente"
                    }
                }
            }
        ),
    ]


def get_analytics_handlers():
    """Restituisce il dizionario di handler per analytics."""
    return {
        "get_revenue_by_month": handle_get_revenue_by_month,
        "get_revenue_by_client": handle_get_revenue_by_client,
        "get_yearly_stats": handle_get_yearly_stats,
    }
