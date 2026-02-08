"""
Tools per gestione clienti.
"""

from datetime import datetime, timedelta
from mcp.types import Tool, TextContent
from fattureincloud_python_sdk.api import clients_api, issued_documents_api

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


async def handle_get_clients(arguments: dict) -> list[TextContent]:
    """Lista clienti."""
    name_filter = arguments.get("name")
    limit = arguments.get("limit", 50)

    with get_api_client() as api_client:
        api = clients_api.ClientsApi(api_client)

        try:
            q = None
            if name_filter:
                q = f"name =~ '{name_filter}'"

            # Loop paginazione per recuperare TUTTI i clienti
            clients = []
            page = 1

            while True:
                response = api.list_clients(
                    company_id=COMPANY_ID,
                    q=q,
                    page=page,
                    per_page=100,
                    fieldset="detailed"
                )

                if response.data:
                    clients.extend(response.data)

                # Verifica se ci sono altre pagine
                if page >= response.last_page:
                    break

                page += 1

            if not clients:
                output = "Nessun cliente trovato."
            else:
                output = f"Trovati {len(clients)} clienti:\n\n"
                for client in clients:
                    output += f"- ID {client.id} - {client.name}\n"

                    # Codice cliente
                    if client.code:
                        output += f"  Codice: {client.code}\n"

                    # Dati fiscali
                    if client.vat_number:
                        output += f"  P.IVA: {client.vat_number}\n"
                    if client.tax_code and client.tax_code != client.vat_number:
                        output += f"  C.F.: {client.tax_code}\n"

                    # Indirizzo completo
                    if client.address_street:
                        output += f"  Indirizzo: {client.address_street}\n"
                    if client.address_postal_code or client.address_city:
                        addr_line = f"    {client.address_postal_code or ''} {client.address_city or ''}"
                        if client.address_province:
                            addr_line += f" ({client.address_province})"
                        output += addr_line + "\n"
                    if client.country:
                        output += f"    {client.country}\n"

                    # Contatti
                    if client.certified_email:
                        output += f"  PEC: {client.certified_email}\n"
                    if client.email:
                        output += f"  Email: {client.email}\n"
                    if client.phone:
                        output += f"  Telefono: {client.phone}\n"
                    if client.fax:
                        output += f"  Fax: {client.fax}\n"

                    # Persona di contatto
                    if client.contact_person:
                        output += f"  Referente: {client.contact_person}\n"

                    # Codice destinatario (fatturazione elettronica)
                    if client.ei_code:
                        output += f"  Codice destinatario: {client.ei_code}\n"
                    if client.e_invoice:
                        output += f"  Fatturazione elettronica: Abilitata\n"

                    # Termini di pagamento predefiniti
                    if client.default_payment_terms and client.default_payment_terms > 0:
                        output += f"  Giorni pagamento: {client.default_payment_terms}\n"
                    if client.default_payment_terms_type:
                        output += f"  Tipo pagamento: {client.default_payment_terms_type}\n"

                    # Banca predefinita
                    if client.bank_name:
                        output += f"  Banca: {client.bank_name}\n"
                    if client.bank_iban:
                        output += f"  IBAN: {client.bank_iban}\n"
                    if client.bank_swift_code:
                        output += f"  SWIFT: {client.bank_swift_code}\n"

                    # Note
                    if client.notes:
                        output += f"  Note: {client.notes}\n"

                    output += "\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


async def handle_get_client_invoices(arguments: dict) -> list[TextContent]:
    """Fatture per cliente specifico."""
    client_name = arguments.get("client_name")
    from_date = arguments.get("from_date")
    to_date = arguments.get("to_date")
    limit = arguments.get("limit", 50)

    if not client_name:
        return [TextContent(type="text", text="Errore: client_name mancante")]

    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        try:
            if not to_date:
                to_date = datetime.now().strftime("%Y-%m-%d")
            if not from_date:
                from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

            q = f"date >= '{from_date}' and date <= '{to_date}' and entity.name =~ '{client_name}'"

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

            if not invoices:
                output = f"Nessuna fattura trovata per il cliente '{client_name}'."
            else:
                total_amount = sum(inv.amount_gross or 0 for inv in invoices)
                total_paid = 0.0
                total_remaining = 0.0

                for inv in invoices:
                    pay_info = get_payment_info(inv)
                    total_paid += pay_info["paid"]
                    total_remaining += pay_info["remaining"]

                output = f"Fatture per cliente: {client_name}\n"
                output += f"{'=' * 40}\n"
                output += f"Periodo: {from_date} - {to_date}\n\n"
                output += f"Totale fatture: {len(invoices)}\n"
                output += f"Importo totale: {total_amount:.2f} EUR\n"
                output += f"Pagato: {total_paid:.2f} EUR\n"
                output += f"Da pagare: {total_remaining:.2f} EUR\n\n"
                output += "DETTAGLIO:\n\n"

                for inv in invoices:
                    pay_info = get_payment_info(inv)
                    output += f"- ID {inv.id} - N. {_get_full_invoice_number(inv)} del {inv.var_date or 'N/A'}\n"

                    # Importi con dettaglio
                    output += f"  Imponibile: {inv.amount_net or 0:.2f} EUR\n"
                    output += f"  IVA: {inv.amount_vat or 0:.2f} EUR\n"
                    output += f"  Totale: {inv.amount_gross or 0:.2f} EUR\n"

                    # Stato pagamento
                    output += f"  Stato: {pay_info['status_display']}\n"
                    if pay_info["remaining"] > 0:
                        output += f"  Da incassare: {pay_info['remaining']:.2f} EUR\n"
                    if pay_info["due_date"]:
                        output += f"  Scadenza: {pay_info['due_date']}\n"

                    # Oggetto se presente
                    if inv.subject:
                        output += f"  Oggetto: {inv.subject}\n"

                    output += "\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


def get_client_tools():
    """Restituisce la lista di tool per clienti."""
    return [
        Tool(
            name="get_clients",
            description="Lista clienti con filtro opzionale per nome",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Filtra per nome cliente (ricerca parziale)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Numero massimo risultati, default: 50"
                    }
                }
            }
        ),
        Tool(
            name="get_client_invoices",
            description="Tutte le fatture per un cliente specifico con riepilogo",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_name": {
                        "type": "string",
                        "description": "Nome del cliente"
                    },
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
                        "description": "Numero massimo risultati, default: 50"
                    }
                },
                "required": ["client_name"]
            }
        ),
    ]


def get_client_handlers():
    """Restituisce il dizionario di handler per clienti."""
    return {
        "get_clients": handle_get_clients,
        "get_client_invoices": handle_get_client_invoices,
    }
