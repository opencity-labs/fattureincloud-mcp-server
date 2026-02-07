"""
Tools per gestione fatture emesse (issued documents).
"""

from datetime import datetime, timedelta
from mcp.types import Tool, TextContent
from fattureincloud_python_sdk.api import issued_documents_api

from ..config import COMPANY_ID, get_api_client
from ..utils import get_payment_info


async def handle_get_invoices(arguments: dict) -> list[TextContent]:
    """Lista fatture emesse con filtri."""
    status = arguments.get("status")
    from_date = arguments.get("from_date")
    to_date = arguments.get("to_date")
    client_name = arguments.get("client_name")
    limit = arguments.get("limit", 50)

    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        if not to_date:
            to_date = datetime.now().strftime("%Y-%m-%d")
        if not from_date:
            from_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

        q = f"date >= '{from_date}' and date <= '{to_date}'"
        if client_name:
            q += f" and entity.name =~ '{client_name}'"

        try:
            # Recupera TUTTI i tipi di documento facendo chiamate separate
            # L'API richiede type obbligatorio, quindi facciamo più chiamate
            invoices = []

            # Tipi di documento da recuperare
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
                        # Se il tipo non esiste o non è supportato, continua con il prossimo
                        if "404" in str(e) or "not found" in str(e).lower():
                            break
                        # Per altri errori, propagali
                        raise
            filtered_invoices = []

            for inv in invoices:
                pay_info = get_payment_info(inv)

                if status and pay_info["status"] != status:
                    continue

                filtered_invoices.append(inv)

            if not filtered_invoices:
                output = "Nessuna fattura trovata con i filtri specificati."
            else:
                output = f"Trovate {len(filtered_invoices)} fatture:\n\n"

                for inv in filtered_invoices:
                    pay_info = get_payment_info(inv)

                    output += f"- ID {inv.id} - N. {inv.number or 'N/A'} del {inv.var_date or 'N/A'}\n"

                    # Cliente con dettagli
                    if inv.entity:
                        output += f"  Cliente: {inv.entity.name}\n"
                        if inv.entity.vat_number:
                            output += f"  P.IVA: {inv.entity.vat_number}\n"
                        if inv.entity.tax_code and inv.entity.tax_code != inv.entity.vat_number:
                            output += f"  C.F.: {inv.entity.tax_code}\n"

                    # Tipo e numerazione
                    if inv.type:
                        output += f"  Tipo: {inv.type}\n"
                    if inv.numeration:
                        output += f"  Numerazione: {inv.numeration}\n"

                    # Importi con imponibile e IVA
                    output += f"  Imponibile: {inv.amount_net or 0:.2f} EUR\n"
                    output += f"  IVA: {inv.amount_vat or 0:.2f} EUR\n"
                    output += f"  Totale: {inv.amount_gross or 0:.2f} EUR\n"

                    # Ritenute
                    if inv.amount_withholding_tax and inv.amount_withholding_tax > 0:
                        output += f"  Ritenuta: {inv.amount_withholding_tax:.2f} EUR\n"

                    # Altri importi
                    if inv.amount_other_withholding_tax and inv.amount_other_withholding_tax > 0:
                        output += f"  Altre ritenute: {inv.amount_other_withholding_tax:.2f} EUR\n"

                    # Stato pagamento
                    output += f"  Stato pagamento: {pay_info['status_display']}\n"
                    if pay_info["remaining"] > 0:
                        output += f"  Da incassare: {pay_info['remaining']:.2f} EUR\n"
                    if pay_info["due_date"]:
                        output += f"  Scadenza: {pay_info['due_date']}\n"

                    # E-invoice
                    if inv.e_invoice:
                        output += f"  Fattura elettronica: Sì\n"

                    # Oggetto
                    if inv.subject:
                        output += f"  Oggetto: {inv.subject}\n"

                    output += "\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


async def handle_get_invoice(arguments: dict) -> list[TextContent]:
    """Dettaglio completo di una singola fattura."""
    invoice_id = arguments.get("invoice_id")

    if not invoice_id:
        return [TextContent(type="text", text="Errore: invoice_id mancante")]

    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        try:
            response = api.get_issued_document(
                company_id=COMPANY_ID,
                document_id=invoice_id,
                fieldset="detailed"
            )

            inv = response.data
            if not inv:
                return [TextContent(type="text", text="Fattura non trovata")]

            pay_info = get_payment_info(inv)

            output = f"FATTURA #{inv.number or 'N/A'} - ID {inv.id}\n"
            output += f"{'=' * 60}\n\n"

            # Tipo e numerazione
            if inv.type:
                output += f"Tipo: {inv.type}\n"
            if inv.numeration:
                output += f"Numerazione: {inv.numeration}\n"

            # Date
            output += f"Data emissione: {inv.var_date or 'N/A'}\n"
            if pay_info['due_date']:
                output += f"Scadenza: {pay_info['due_date']}\n"

            # E-invoice
            if inv.e_invoice:
                output += f"Fattura elettronica: Sì\n"

            output += "\n"

            # Cliente
            output += f"CLIENTE:\n"
            if inv.entity:
                output += f"Nome: {inv.entity.name}\n"
                if inv.entity.vat_number:
                    output += f"P.IVA: {inv.entity.vat_number}\n"
                if inv.entity.tax_code and inv.entity.tax_code != inv.entity.vat_number:
                    output += f"C.F.: {inv.entity.tax_code}\n"

                # Indirizzo completo
                if inv.entity.address_street:
                    output += f"Indirizzo: {inv.entity.address_street}\n"
                if inv.entity.address_postal_code or inv.entity.address_city:
                    output += f"  {inv.entity.address_postal_code or ''} {inv.entity.address_city or ''}"
                    if inv.entity.address_province:
                        output += f" ({inv.entity.address_province})"
                    output += "\n"
                if inv.entity.country:
                    output += f"  {inv.entity.country}\n"

                # Contatti
                if inv.entity.certified_email:
                    output += f"PEC: {inv.entity.certified_email}\n"
                if inv.entity.email:
                    output += f"Email: {inv.entity.email}\n"
                if inv.entity.phone:
                    output += f"Telefono: {inv.entity.phone}\n"

                # Codice destinatario
                if inv.entity.ei_code:
                    output += f"Codice destinatario: {inv.entity.ei_code}\n"
            else:
                output += "N/A\n"

            output += "\n"

            # Oggetto
            if inv.subject:
                output += f"OGGETTO: {inv.subject}\n\n"
            if inv.visible_subject:
                output += f"OGGETTO VISIBILE: {inv.visible_subject}\n\n"

            # Importi
            output += f"IMPORTI:\n"
            output += f"Imponibile: {inv.amount_net or 0:.2f} EUR\n"
            output += f"IVA: {inv.amount_vat or 0:.2f} EUR\n"

            if inv.amount_withholding_tax and inv.amount_withholding_tax > 0:
                output += f"Ritenuta d'acconto: {inv.amount_withholding_tax:.2f} EUR\n"
                if inv.withholding_tax:
                    output += f"  Aliquota ritenuta: {inv.withholding_tax}%\n"

            if inv.amount_other_withholding_tax and inv.amount_other_withholding_tax > 0:
                output += f"Altre ritenute: {inv.amount_other_withholding_tax:.2f} EUR\n"

            if inv.stamp_duty and inv.stamp_duty > 0:
                output += f"Bollo: {inv.stamp_duty:.2f} EUR\n"

            output += f"TOTALE: {inv.amount_gross or 0:.2f} EUR\n"

            if inv.amount_due_discount and inv.amount_due_discount != 0:
                output += f"Sconto globale: {inv.amount_due_discount:.2f} EUR\n"

            output += "\n"

            # Stato pagamenti
            output += f"PAGAMENTI:\n"
            output += f"Pagato: {pay_info['paid']:.2f} EUR\n"
            output += f"Da incassare: {pay_info['remaining']:.2f} EUR\n"
            output += f"Stato: {pay_info['status_display']}\n"

            # Dettaglio pagamenti
            if inv.payments_list and len(inv.payments_list) > 0:
                output += "\nDettaglio pagamenti:\n"
                for payment in inv.payments_list:
                    status_map = {'paid': 'Pagato', 'not_paid': 'Da pagare', 'reversed': 'Stornato'}
                    status = status_map.get(payment.status, payment.status)
                    output += f"- {payment.amount:.2f} EUR - Scadenza: {payment.due_date} - {status}\n"
                    if payment.paid_date:
                        output += f"  Pagato il: {payment.paid_date}\n"
                    if payment.payment_terms:
                        output += f"  Modalità: {payment.payment_terms.get('name', 'N/A')}\n"

            output += "\n"

            # Voci/righe fattura
            if inv.items_list:
                output += f"RIGHE FATTURA:\n"
                for i, item in enumerate(inv.items_list, 1):
                    output += f"{i}. {item.name or 'N/A'}\n"
                    if item.description:
                        output += f"   Descrizione: {item.description}\n"
                    if item.product_id:
                        output += f"   Codice prodotto: {item.product_id}\n"

                    output += f"   Quantità: {item.qty or 0}\n"
                    output += f"   Prezzo unitario: {item.net_price or 0:.2f} EUR\n"

                    if item.discount and item.discount > 0:
                        output += f"   Sconto: {item.discount}%\n"

                    if item.vat:
                        output += f"   IVA: {item.vat.get('value', 0)}%\n"

                    subtotal = (item.net_price or 0) * (item.qty or 0)
                    if item.discount:
                        subtotal *= (1 - item.discount / 100)
                    output += f"   Subtotale: {subtotal:.2f} EUR\n\n"

            # Note
            if inv.notes:
                output += f"NOTE:\n{inv.notes}\n\n"

            # Allegati
            if inv.attachment_url:
                output += f"ALLEGATO: {inv.attachment_url}\n\n"

            # Informazioni sistema
            if inv.created_at:
                output += f"Creata il: {inv.created_at}\n"
            if inv.updated_at:
                output += f"Aggiornata il: {inv.updated_at}\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


def get_invoice_tools():
    """Restituisce la lista di tool per fatture emesse."""
    return [
        Tool(
            name="get_invoices",
            description="Lista fatture emesse con filtri (status, date, cliente)",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filtra per stato: paid, not_paid, partially_paid",
                        "enum": ["paid", "not_paid", "partially_paid"]
                    },
                    "from_date": {
                        "type": "string",
                        "description": "Data inizio (YYYY-MM-DD), default: ultimi 90 giorni"
                    },
                    "to_date": {
                        "type": "string",
                        "description": "Data fine (YYYY-MM-DD), default: oggi"
                    },
                    "client_name": {
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
            name="get_invoice",
            description="Dettaglio completo di una singola fattura",
            inputSchema={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "integer",
                        "description": "ID della fattura"
                    }
                },
                "required": ["invoice_id"]
            }
        ),
    ]


def get_invoice_handlers():
    """Restituisce il dizionario di handler per fatture emesse."""
    return {
        "get_invoices": handle_get_invoices,
        "get_invoice": handle_get_invoice,
    }
