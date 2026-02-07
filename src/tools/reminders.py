"""
Tools per gestione solleciti e analisi crediti.

Questo modulo fornisce strumenti per:
- Fatture scadute con netting automatico delle note di credito
- Aging report (analisi anzianità crediti)
- Dati strutturati per generazione solleciti
- Analisi comportamento pagamenti cliente
- Coda priorità solleciti
"""

from datetime import datetime, timedelta
from collections import defaultdict
from mcp.types import Tool, TextContent
from fattureincloud_python_sdk.api import issued_documents_api

from ..config import COMPANY_ID, get_api_client
from ..utils import get_payment_info


def _fetch_all_issued_documents(api, from_date: str, to_date: str, doc_types: list) -> list:
    """Helper per recuperare tutti i documenti emessi con paginazione."""
    all_docs = []
    q = f"date >= '{from_date}' and date <= '{to_date}'"

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
                    all_docs.extend(response.data)

                if page >= response.last_page:
                    break
                page += 1
            except Exception as e:
                if "404" in str(e) or "not found" in str(e).lower():
                    break
                raise

    return all_docs


def _apply_netting_fifo(overdue_items: list, credit_notes: list) -> tuple[list, list, dict]:
    """
    Applica netting FIFO tra fatture scadute e note di credito.

    Logica:
    1. Raggruppa fatture e NC per cliente
    2. Per ogni cliente, ordina fatture per data (più vecchie prima)
    3. Somma le NC del cliente
    4. Applica il credito NC alle fatture in ordine FIFO:
       - Se NC >= fattura, la fattura viene completamente coperta → esclusa
       - Se NC copre parzialmente, aggiorna il remaining

    Args:
        overdue_items: Lista di dict con chiavi 'invoice', 'pay_info', 'days_overdue'
        credit_notes: Lista di note di credito

    Returns:
        tuple: (fatture_con_saldo_aggiornato, dettagli_netting, nc_per_cliente)
    """
    # Raggruppa NC per cliente
    nc_by_client = defaultdict(list)
    for cn in credit_notes:
        if cn.entity and cn.entity.name:
            nc_by_client[cn.entity.name.lower()].append(cn)

    # Raggruppa fatture per cliente
    invoices_by_client = defaultdict(list)
    for item in overdue_items:
        if item["invoice"].entity and item["invoice"].entity.name:
            client_name = item["invoice"].entity.name.lower()
            invoices_by_client[client_name].append(item)

    result_items = []
    netting_details = []

    for client_lower, items in invoices_by_client.items():
        # Ordina fatture per data (più vecchie prima) usando var_date
        items_sorted = sorted(items, key=lambda x: x["invoice"].var_date or datetime.min)

        # Calcola totale NC per questo cliente (usa imponibile/amount_net)
        client_ncs = nc_by_client.get(client_lower, [])
        total_nc_credit = sum(abs(cn.amount_net or 0) for cn in client_ncs)

        # Applica netting FIFO
        for item in items_sorted:
            remaining = item["pay_info"]["remaining"]
            inv = item["invoice"]

            if total_nc_credit <= 0:
                # Nessun credito NC rimasto, fattura resta com'è
                result_items.append(item)
            elif total_nc_credit >= remaining - 0.01:  # Tolleranza per arrotondamenti
                # NC copre completamente questa fattura → esclusa
                total_nc_credit -= remaining
                netting_details.append({
                    "invoice": inv,
                    "invoice_number": inv.number,
                    "invoice_date": str(inv.var_date) if inv.var_date else None,
                    "due_date": item["pay_info"]["due_date"],
                    "original_remaining": remaining,
                    "covered_amount": remaining,
                    "new_remaining": 0,
                    "fully_covered": True,
                    "client": inv.entity.name,
                    "credit_notes_used": client_ncs  # NC usate per questo cliente
                })
            else:
                # NC copre parzialmente → aggiorna remaining
                new_remaining = remaining - total_nc_credit
                netting_details.append({
                    "invoice": inv,
                    "invoice_number": inv.number,
                    "invoice_date": str(inv.var_date) if inv.var_date else None,
                    "due_date": item["pay_info"]["due_date"],
                    "original_remaining": remaining,
                    "covered_amount": total_nc_credit,
                    "new_remaining": new_remaining,
                    "fully_covered": False,
                    "client": inv.entity.name,
                    "credit_notes_used": client_ncs
                })
                # Crea copia dell'item con remaining aggiornato solo se residuo > 0
                if new_remaining > 0.01:  # Tolleranza per arrotondamenti
                    updated_item = {
                        "invoice": inv,
                        "pay_info": {**item["pay_info"], "remaining": new_remaining},
                        "days_overdue": item["days_overdue"]
                    }
                    result_items.append(updated_item)
                total_nc_credit = 0

    return result_items, netting_details, dict(nc_by_client)


async def handle_get_overdue_invoices_with_netting(arguments: dict) -> list[TextContent]:
    """
    Fatture scadute con netting automatico delle note di credito.

    Logica FIFO:
    1. Recupera tutte le fatture emesse (ultimi 5 anni)
    2. Recupera tutte le note di credito
    3. Per ogni cliente, somma le NC e le applica alle fatture più vecchie prima
    4. Fatture completamente coperte vengono escluse
    5. Fatture parzialmente coperte mostrano solo il residuo
    """
    limit = arguments.get("limit", 50)
    include_netting_details = arguments.get("include_netting_details", True)

    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        try:
            # Range: ultimi 5 anni
            to_date = datetime.now().strftime("%Y-%m-%d")
            from_date = (datetime.now() - timedelta(days=1825)).strftime("%Y-%m-%d")

            # Recupera fatture e note di credito
            invoices = _fetch_all_issued_documents(api, from_date, to_date, ["invoice"])
            credit_notes = _fetch_all_issued_documents(api, from_date, to_date, ["credit_note"])

            today = datetime.now().date()

            # Trova fatture scadute non pagate
            overdue_invoices = []
            for inv in invoices:
                pay_info = get_payment_info(inv)
                if pay_info["due_date"] and pay_info["remaining"] > 0:
                    due_date = datetime.strptime(pay_info["due_date"], "%Y-%m-%d").date()
                    if due_date < today:
                        days_overdue = (today - due_date).days
                        overdue_invoices.append({
                            "invoice": inv,
                            "pay_info": pay_info,
                            "days_overdue": days_overdue
                        })

            # Applica netting FIFO
            filtered_overdue, netting_details, nc_by_client = _apply_netting_fifo(overdue_invoices, credit_notes)

            # Ordina per giorni di ritardo
            filtered_overdue.sort(key=lambda x: x["days_overdue"], reverse=True)
            filtered_overdue = filtered_overdue[:limit]

            # Helper per formattare una fattura
            def format_invoice_line(item):
                inv = item["invoice"]
                lines = []
                lines.append(f"  - N. {inv.number} | {inv.entity.name if inv.entity else 'N/A'}")
                lines.append(f"    Emissione: {inv.var_date} | Scadenza: {item['pay_info']['due_date']} ({item['days_overdue']} gg)")
                lines.append(f"    Da incassare: {item['pay_info']['remaining']:.2f} EUR")
                return "\n".join(lines)

            # Genera output
            if not filtered_overdue:
                output = "Nessuna fattura scaduta trovata (dopo netting NC).\n"
            else:
                total_overdue = sum(item["pay_info"]["remaining"] for item in filtered_overdue)

                output = f"FATTURE SCADUTE (con netting NC automatico FIFO)\n"
                output += f"{'=' * 60}\n\n"
                output += f"Fatture scadute: {len(filtered_overdue)}\n"
                output += f"Totale da incassare: {total_overdue:.2f} EUR\n\n"

                # Raggruppa per fascia
                critical = [i for i in filtered_overdue if i["days_overdue"] > 90]
                urgent = [i for i in filtered_overdue if 31 <= i["days_overdue"] <= 90]
                recent = [i for i in filtered_overdue if i["days_overdue"] <= 30]

                if critical:
                    output += f"🔴 CRITICHE (oltre 90 giorni): {len(critical)} fatture\n"
                    for item in critical:
                        output += format_invoice_line(item) + "\n"
                    output += "\n"

                if urgent:
                    output += f"🟡 URGENTI (31-90 giorni): {len(urgent)} fatture\n"
                    for item in urgent:
                        output += format_invoice_line(item) + "\n"
                    output += "\n"

                if recent:
                    output += f"🟢 RECENTI (1-30 giorni): {len(recent)} fatture\n"
                    for item in recent:
                        output += format_invoice_line(item) + "\n"
                    output += "\n"

            # Sezione netting
            if include_netting_details and netting_details:
                fully_covered = [n for n in netting_details if n["fully_covered"]]
                partially_covered = [n for n in netting_details if not n["fully_covered"]]
                total_covered = sum(n["covered_amount"] for n in netting_details)

                output += f"\n{'=' * 60}\n"
                output += f"NETTING APPLICATO (FIFO per cliente)\n"
                output += f"Totale compensato: {total_covered:.2f} EUR\n\n"

                # Raggruppa per cliente per mostrare NC usate
                clients_shown = set()

                if fully_covered:
                    output += f"FATTURE COMPLETAMENTE COPERTE: {len(fully_covered)}\n"
                    for n in fully_covered:
                        output += f"  - Fattura {n['invoice_number']} ({n['client']})\n"
                        output += f"    Emissione: {n['invoice_date']} | Scadenza: {n['due_date']}\n"
                        output += f"    Importo: {n['original_remaining']:.2f} EUR → ESCLUSA\n"

                        # Mostra NC usate per questo cliente (solo la prima volta)
                        client_lower = n['client'].lower()
                        if client_lower not in clients_shown and n.get('credit_notes_used'):
                            clients_shown.add(client_lower)
                            output += f"    Compensata con NC:\n"
                            for cn in n['credit_notes_used']:
                                cn_amount = abs(cn.amount_net or 0)
                                output += f"      • NC {cn.number} del {cn.var_date} - {cn_amount:.2f} EUR\n"
                                if cn.subject:
                                    output += f"        ({cn.subject[:50]}{'...' if len(cn.subject) > 50 else ''})\n"
                    output += "\n"

                if partially_covered:
                    output += f"FATTURE PARZIALMENTE COPERTE: {len(partially_covered)}\n"
                    for n in partially_covered:
                        output += f"  - Fattura {n['invoice_number']} ({n['client']})\n"
                        output += f"    Emissione: {n['invoice_date']} | Scadenza: {n['due_date']}\n"
                        output += f"    Originale: {n['original_remaining']:.2f} EUR\n"
                        output += f"    Compensato: {n['covered_amount']:.2f} EUR\n"
                        output += f"    Residuo: {n['new_remaining']:.2f} EUR\n"

                        # Mostra NC usate
                        client_lower = n['client'].lower()
                        if client_lower not in clients_shown and n.get('credit_notes_used'):
                            clients_shown.add(client_lower)
                            output += f"    Compensata con NC:\n"
                            for cn in n['credit_notes_used']:
                                cn_amount = abs(cn.amount_net or 0)
                                output += f"      • NC {cn.number} del {cn.var_date} - {cn_amount:.2f} EUR\n"
                    output += "\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


async def handle_get_aging_report(arguments: dict) -> list[TextContent]:
    """
    Aging report - analisi anzianità crediti per fascia temporale.

    Fasce standard:
    - 1-30 giorni
    - 31-60 giorni
    - 61-90 giorni
    - 90+ giorni

    Include netting FIFO automatico NC.
    """
    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        try:
            to_date = datetime.now().strftime("%Y-%m-%d")
            from_date = (datetime.now() - timedelta(days=1825)).strftime("%Y-%m-%d")

            invoices = _fetch_all_issued_documents(api, from_date, to_date, ["invoice"])
            credit_notes = _fetch_all_issued_documents(api, from_date, to_date, ["credit_note"])

            today = datetime.now().date()

            # Trova fatture scadute
            overdue_invoices = []
            for inv in invoices:
                pay_info = get_payment_info(inv)
                if pay_info["due_date"] and pay_info["remaining"] > 0:
                    due_date = datetime.strptime(pay_info["due_date"], "%Y-%m-%d").date()
                    if due_date < today:
                        days_overdue = (today - due_date).days
                        overdue_invoices.append({
                            "invoice": inv,
                            "pay_info": pay_info,
                            "days_overdue": days_overdue
                        })

            # Applica netting FIFO
            filtered_overdue, netting_details, _ = _apply_netting_fifo(overdue_invoices, credit_notes)

            # Raggruppa per fascia
            buckets = {
                "1-30": {"count": 0, "amount": 0.0, "items": []},
                "31-60": {"count": 0, "amount": 0.0, "items": []},
                "61-90": {"count": 0, "amount": 0.0, "items": []},
                "90+": {"count": 0, "amount": 0.0, "items": []},
            }

            for item in filtered_overdue:
                days = item["days_overdue"]
                amount = item["pay_info"]["remaining"]

                if days <= 30:
                    bucket = "1-30"
                elif days <= 60:
                    bucket = "31-60"
                elif days <= 90:
                    bucket = "61-90"
                else:
                    bucket = "90+"

                buckets[bucket]["count"] += 1
                buckets[bucket]["amount"] += amount
                buckets[bucket]["items"].append(item)

            # Genera output
            total_count = sum(b["count"] for b in buckets.values())
            total_amount = sum(b["amount"] for b in buckets.values())
            total_netting = sum(n["covered_amount"] for n in netting_details)

            output = f"AGING REPORT - {today.strftime('%d/%m/%Y')}\n"
            output += f"{'=' * 60}\n\n"
            output += f"Totale fatture scadute: {total_count}\n"
            output += f"Totale da incassare: € {total_amount:,.2f}\n"
            output += f"(Netting FIFO NC applicato: € {total_netting:,.2f})\n\n"

            output += f"{'Fascia':<15} {'Fatture':>10} {'Importo':>20} {'%':>8}\n"
            output += f"{'-' * 55}\n"

            for bucket_name, bucket_data in buckets.items():
                pct = (bucket_data["amount"] / total_amount * 100) if total_amount > 0 else 0
                warning = " ⚠️" if bucket_name == "90+" and bucket_data["count"] > 0 else ""
                output += f"{bucket_name + ' giorni':<15} {bucket_data['count']:>10} {bucket_data['amount']:>17,.2f} € {pct:>7.1f}%{warning}\n"

            output += f"{'-' * 55}\n"
            output += f"{'TOTALE':<15} {total_count:>10} {total_amount:>17,.2f} € {'100.0':>7}%\n"

            # Dettaglio per fascia critica
            if buckets["90+"]["items"]:
                output += f"\n\n⚠️ DETTAGLIO FASCIA CRITICA (90+ giorni):\n"
                output += f"{'-' * 40}\n"
                for item in sorted(buckets["90+"]["items"], key=lambda x: x["days_overdue"], reverse=True):
                    inv = item["invoice"]
                    output += f"- {inv.entity.name if inv.entity else 'N/A'}\n"
                    output += f"  Fattura {inv.number} - {item['days_overdue']} giorni\n"
                    output += f"  Da incassare: € {item['pay_info']['remaining']:,.2f}\n\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


async def handle_get_reminder_data(arguments: dict) -> list[TextContent]:
    """
    Dati strutturati per generare solleciti.

    Restituisce per ogni cliente con fatture scadute:
    - Dati anagrafici completi (nome, PEC, email, referente)
    - Lista fatture scadute con dettagli
    - Totale da incassare
    - Giorni medi di ritardo
    """
    client_name = arguments.get("client_name")
    min_days_overdue = arguments.get("min_days_overdue", 1)

    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        try:
            to_date = datetime.now().strftime("%Y-%m-%d")
            from_date = (datetime.now() - timedelta(days=1825)).strftime("%Y-%m-%d")

            invoices = _fetch_all_issued_documents(api, from_date, to_date, ["invoice"])
            credit_notes = _fetch_all_issued_documents(api, from_date, to_date, ["credit_note"])

            today = datetime.now().date()

            # Trova fatture scadute
            overdue_invoices = []
            for inv in invoices:
                pay_info = get_payment_info(inv)
                if pay_info["due_date"] and pay_info["remaining"] > 0:
                    due_date = datetime.strptime(pay_info["due_date"], "%Y-%m-%d").date()
                    if due_date < today:
                        days_overdue = (today - due_date).days
                        if days_overdue >= min_days_overdue:
                            overdue_invoices.append({
                                "invoice": inv,
                                "pay_info": pay_info,
                                "days_overdue": days_overdue
                            })

            # Applica netting FIFO
            filtered_overdue, _, _ = _apply_netting_fifo(overdue_invoices, credit_notes)

            # Filtra per cliente se specificato
            if client_name:
                filtered_overdue = [
                    item for item in filtered_overdue
                    if item["invoice"].entity and
                    client_name.lower() in item["invoice"].entity.name.lower()
                ]

            # Raggruppa per cliente
            by_client = defaultdict(list)
            for item in filtered_overdue:
                if item["invoice"].entity:
                    by_client[item["invoice"].entity.name].append(item)

            if not by_client:
                output = "Nessun cliente con fatture scadute trovato.\n"
            else:
                output = f"DATI PER SOLLECITI - {today.strftime('%d/%m/%Y')}\n"
                output += f"{'=' * 60}\n\n"
                output += f"Clienti con fatture scadute: {len(by_client)}\n\n"

                for client, items in sorted(by_client.items(),
                                            key=lambda x: sum(i["pay_info"]["remaining"] for i in x[1]),
                                            reverse=True):
                    total_amount = sum(i["pay_info"]["remaining"] for i in items)
                    avg_days = sum(i["days_overdue"] for i in items) / len(items)

                    # Prendi dati anagrafici dal primo documento
                    entity = items[0]["invoice"].entity

                    output += f"{'─' * 60}\n"
                    output += f"CLIENTE: {client}\n"
                    output += f"{'─' * 60}\n\n"

                    # Dati anagrafici
                    output += "ANAGRAFICA:\n"
                    if entity.vat_number:
                        output += f"  P.IVA: {entity.vat_number}\n"
                    if entity.tax_code and entity.tax_code != entity.vat_number:
                        output += f"  C.F.: {entity.tax_code}\n"
                    if entity.certified_email:
                        output += f"  PEC: {entity.certified_email}\n"
                    if entity.email:
                        output += f"  Email: {entity.email}\n"
                    if entity.phone:
                        output += f"  Telefono: {entity.phone}\n"
                    if entity.contact_person:
                        output += f"  Referente: {entity.contact_person}\n"
                    if entity.address_street:
                        addr = entity.address_street
                        if entity.address_postal_code:
                            addr += f", {entity.address_postal_code}"
                        if entity.address_city:
                            addr += f" {entity.address_city}"
                        if entity.address_province:
                            addr += f" ({entity.address_province})"
                        output += f"  Indirizzo: {addr}\n"

                    output += f"\nRIEPILOGO:\n"
                    output += f"  Fatture scadute: {len(items)}\n"
                    output += f"  Totale da incassare: € {total_amount:,.2f}\n"
                    output += f"  Giorni medi ritardo: {avg_days:.0f}\n"

                    output += f"\nDETTAGLIO FATTURE:\n"
                    for item in sorted(items, key=lambda x: x["days_overdue"], reverse=True):
                        inv = item["invoice"]
                        output += f"  - N. {inv.number} del {inv.var_date}\n"
                        output += f"    Scadenza: {item['pay_info']['due_date']} ({item['days_overdue']} giorni fa)\n"
                        output += f"    Importo: € {item['pay_info']['remaining']:,.2f}\n"
                        if inv.subject:
                            output += f"    Oggetto: {inv.subject[:50]}...\n" if len(inv.subject) > 50 else f"    Oggetto: {inv.subject}\n"

                    output += "\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


async def handle_get_client_payment_behavior(arguments: dict) -> list[TextContent]:
    """
    Analisi comportamento pagamenti per cliente.

    Calcola:
    - DSO medio (Days Sales Outstanding)
    - % fatture pagate in ritardo
    - Trend (migliora/peggiora/stabile)
    - Rating affidabilità
    """
    client_name = arguments.get("client_name")

    if not client_name:
        return [TextContent(type="text", text="Errore: client_name richiesto")]

    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        try:
            # Ultimi 3 anni per trend
            to_date = datetime.now().strftime("%Y-%m-%d")
            from_date = (datetime.now() - timedelta(days=1095)).strftime("%Y-%m-%d")

            invoices = _fetch_all_issued_documents(api, from_date, to_date, ["invoice"])

            # Filtra per cliente
            client_invoices = [
                inv for inv in invoices
                if inv.entity and client_name.lower() in inv.entity.name.lower()
            ]

            if not client_invoices:
                return [TextContent(type="text", text=f"Nessuna fattura trovata per '{client_name}'")]

            today = datetime.now().date()

            # Analizza pagamenti
            stats_by_year = defaultdict(lambda: {
                "total": 0,
                "paid": 0,
                "late": 0,
                "dso_sum": 0,
                "dso_count": 0
            })

            for inv in client_invoices:
                pay_info = get_payment_info(inv)
                year = inv.var_date.year if inv.var_date else datetime.now().year

                stats_by_year[year]["total"] += 1

                if pay_info["status"] == "paid":
                    stats_by_year[year]["paid"] += 1

                    # Calcola DSO se abbiamo le date
                    if inv.payments_list:
                        for payment in inv.payments_list:
                            if payment.paid_date and payment.due_date:
                                try:
                                    paid_date = datetime.strptime(str(payment.paid_date), "%Y-%m-%d").date()
                                    due_date = datetime.strptime(str(payment.due_date), "%Y-%m-%d").date()
                                    dso = (paid_date - due_date).days
                                    stats_by_year[year]["dso_sum"] += dso
                                    stats_by_year[year]["dso_count"] += 1
                                    if dso > 0:
                                        stats_by_year[year]["late"] += 1
                                except:
                                    pass

            # Calcola metriche aggregate
            total_invoices = sum(s["total"] for s in stats_by_year.values())
            total_paid = sum(s["paid"] for s in stats_by_year.values())
            total_late = sum(s["late"] for s in stats_by_year.values())
            total_dso_sum = sum(s["dso_sum"] for s in stats_by_year.values())
            total_dso_count = sum(s["dso_count"] for s in stats_by_year.values())

            avg_dso = total_dso_sum / total_dso_count if total_dso_count > 0 else 0
            late_pct = (total_late / total_paid * 100) if total_paid > 0 else 0

            # Determina trend
            years = sorted(stats_by_year.keys())
            if len(years) >= 2:
                recent_year = years[-1]
                older_year = years[-2]

                recent_late_pct = (stats_by_year[recent_year]["late"] / stats_by_year[recent_year]["paid"] * 100) if stats_by_year[recent_year]["paid"] > 0 else 0
                older_late_pct = (stats_by_year[older_year]["late"] / stats_by_year[older_year]["paid"] * 100) if stats_by_year[older_year]["paid"] > 0 else 0

                if recent_late_pct < older_late_pct - 10:
                    trend = "📈 IN MIGLIORAMENTO"
                elif recent_late_pct > older_late_pct + 10:
                    trend = "📉 IN PEGGIORAMENTO"
                else:
                    trend = "➡️ STABILE"
            else:
                trend = "➡️ DATI INSUFFICIENTI"

            # Rating
            if avg_dso <= 0 and late_pct < 20:
                rating = "⭐⭐⭐⭐⭐ ECCELLENTE"
            elif avg_dso <= 15 and late_pct < 40:
                rating = "⭐⭐⭐⭐ BUONO"
            elif avg_dso <= 30 and late_pct < 60:
                rating = "⭐⭐⭐ NELLA MEDIA"
            elif avg_dso <= 60:
                rating = "⭐⭐ ATTENZIONE"
            else:
                rating = "⭐ CRITICO"

            # Output
            output = f"ANALISI COMPORTAMENTO PAGAMENTI\n"
            output += f"{'=' * 60}\n"
            output += f"Cliente: {client_name}\n"
            output += f"Periodo analisi: {from_date} - {to_date}\n\n"

            output += f"METRICHE AGGREGATE:\n"
            output += f"  Fatture totali: {total_invoices}\n"
            output += f"  Fatture pagate: {total_paid}\n"
            output += f"  Pagamenti in ritardo: {total_late} ({late_pct:.1f}%)\n"
            output += f"  DSO medio: {avg_dso:.0f} giorni\n\n"

            output += f"VALUTAZIONE:\n"
            output += f"  Rating: {rating}\n"
            output += f"  Trend: {trend}\n\n"

            output += f"DETTAGLIO PER ANNO:\n"
            for year in sorted(stats_by_year.keys(), reverse=True):
                s = stats_by_year[year]
                year_late_pct = (s["late"] / s["paid"] * 100) if s["paid"] > 0 else 0
                year_dso = s["dso_sum"] / s["dso_count"] if s["dso_count"] > 0 else 0
                output += f"  {year}: {s['total']} fatture, {s['late']} ritardi ({year_late_pct:.0f}%), DSO {year_dso:.0f}gg\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


async def handle_get_reminder_priority_queue(arguments: dict) -> list[TextContent]:
    """
    Coda priorità solleciti.

    Classifica clienti da sollecitare basandosi su:
    - Importo * giorni ritardo (weighted score)
    - Storico pagamenti (affidabilità)
    - Numero fatture scadute
    """
    limit = arguments.get("limit", 10)

    with get_api_client() as api_client:
        api = issued_documents_api.IssuedDocumentsApi(api_client)

        try:
            to_date = datetime.now().strftime("%Y-%m-%d")
            from_date = (datetime.now() - timedelta(days=1825)).strftime("%Y-%m-%d")

            invoices = _fetch_all_issued_documents(api, from_date, to_date, ["invoice"])
            credit_notes = _fetch_all_issued_documents(api, from_date, to_date, ["credit_note"])

            today = datetime.now().date()

            # Trova fatture scadute
            overdue_invoices = []
            for inv in invoices:
                pay_info = get_payment_info(inv)
                if pay_info["due_date"] and pay_info["remaining"] > 0:
                    due_date = datetime.strptime(pay_info["due_date"], "%Y-%m-%d").date()
                    if due_date < today:
                        days_overdue = (today - due_date).days
                        overdue_invoices.append({
                            "invoice": inv,
                            "pay_info": pay_info,
                            "days_overdue": days_overdue
                        })

            # Applica netting FIFO
            filtered_overdue, _, _ = _apply_netting_fifo(overdue_invoices, credit_notes)

            # Raggruppa per cliente
            by_client = defaultdict(list)
            for item in filtered_overdue:
                if item["invoice"].entity:
                    by_client[item["invoice"].entity.name].append(item)

            # Calcola priority score per cliente
            client_scores = []
            for client, items in by_client.items():
                total_amount = sum(i["pay_info"]["remaining"] for i in items)
                max_days = max(i["days_overdue"] for i in items)
                avg_days = sum(i["days_overdue"] for i in items) / len(items)
                num_invoices = len(items)

                # Weighted score: importo * log(giorni) * sqrt(num_fatture)
                import math
                priority_score = total_amount * math.log(max_days + 1) * math.sqrt(num_invoices)

                # Urgency level
                if max_days > 90:
                    urgency = "🔴 CRITICO"
                elif max_days > 60:
                    urgency = "🟠 ALTO"
                elif max_days > 30:
                    urgency = "🟡 MEDIO"
                else:
                    urgency = "🟢 BASSO"

                client_scores.append({
                    "client": client,
                    "total_amount": total_amount,
                    "num_invoices": num_invoices,
                    "max_days": max_days,
                    "avg_days": avg_days,
                    "priority_score": priority_score,
                    "urgency": urgency,
                    "entity": items[0]["invoice"].entity
                })

            # Ordina per priority score
            client_scores.sort(key=lambda x: x["priority_score"], reverse=True)
            client_scores = client_scores[:limit]

            # Output
            output = f"CODA PRIORITÀ SOLLECITI - {today.strftime('%d/%m/%Y')}\n"
            output += f"{'=' * 60}\n\n"
            output += f"Top {len(client_scores)} clienti da sollecitare:\n\n"

            for i, cs in enumerate(client_scores, 1):
                output += f"{i}. {cs['urgency']} {cs['client']}\n"
                output += f"   Importo: € {cs['total_amount']:,.2f}\n"
                output += f"   Fatture: {cs['num_invoices']} | Max ritardo: {cs['max_days']} giorni\n"
                if cs["entity"].certified_email:
                    output += f"   PEC: {cs['entity'].certified_email}\n"
                elif cs["entity"].email:
                    output += f"   Email: {cs['entity'].email}\n"
                output += f"   Priority Score: {cs['priority_score']:,.0f}\n\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


def get_reminder_tools():
    """Restituisce la lista di tool per solleciti."""
    return [
        Tool(
            name="get_overdue_invoices_with_netting",
            description="Fatture scadute con netting automatico delle note di credito. Esclude fatture stornate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Numero massimo risultati, default: 50"
                    },
                    "include_netting_details": {
                        "type": "boolean",
                        "description": "Includi dettaglio netting applicato, default: true"
                    }
                }
            }
        ),
        Tool(
            name="get_aging_report",
            description="Aging report - analisi anzianità crediti per fascia (1-30, 31-60, 61-90, 90+ giorni)",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="get_reminder_data",
            description="Dati strutturati per generare solleciti (anagrafica cliente, fatture scadute, contatti)",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_name": {
                        "type": "string",
                        "description": "Nome cliente (opzionale, se omesso restituisce tutti)"
                    },
                    "min_days_overdue": {
                        "type": "integer",
                        "description": "Minimo giorni di ritardo, default: 1"
                    }
                }
            }
        ),
        Tool(
            name="get_client_payment_behavior",
            description="Analisi comportamento pagamenti cliente (DSO, % ritardi, trend, rating)",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_name": {
                        "type": "string",
                        "description": "Nome del cliente da analizzare"
                    }
                },
                "required": ["client_name"]
            }
        ),
        Tool(
            name="get_reminder_priority_queue",
            description="Coda priorità solleciti - classifica clienti da sollecitare per urgenza",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Numero clienti da mostrare, default: 10"
                    }
                }
            }
        ),
    ]


def get_reminder_handlers():
    """Restituisce il dizionario di handler per solleciti."""
    return {
        "get_overdue_invoices_with_netting": handle_get_overdue_invoices_with_netting,
        "get_aging_report": handle_get_aging_report,
        "get_reminder_data": handle_get_reminder_data,
        "get_client_payment_behavior": handle_get_client_payment_behavior,
        "get_reminder_priority_queue": handle_get_reminder_priority_queue,
    }
