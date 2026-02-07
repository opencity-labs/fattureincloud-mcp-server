"""
Utility functions condivise.
"""


def get_payment_info(inv):
    """
    Estrae informazioni pagamento da una fattura.

    Args:
        inv: Oggetto fattura da FattureInCloud SDK

    Returns:
        dict: Info pagamento (total, paid, remaining, status, due_date)
    """
    total = inv.amount_net or 0
    paid = 0
    due_date = None

    # Calcola pagato dalla lista pagamenti
    if hasattr(inv, 'payments_list') and inv.payments_list:
        for p in inv.payments_list:
            if hasattr(p, 'paid_date') and p.paid_date:
                paid += p.amount or 0
            elif hasattr(p, 'status') and p.status == 'paid':
                paid += p.amount or 0
        due_date = inv.payments_list[0].due_date if inv.payments_list else None

    # Fallback: usa is_marked
    if paid == 0 and hasattr(inv, 'is_marked') and inv.is_marked:
        paid = total

    # Determina stato
    if paid >= total and total > 0:
        status = "paid"
        status_display = "PAGATA"
    elif paid > 0:
        status = "partially_paid"
        status_display = "PARZIALE"
    else:
        status = "not_paid"
        status_display = "NON PAGATA"

    return {
        "total": total,
        "paid": paid,
        "remaining": total - paid,
        "status": status,
        "status_display": status_display,
        "due_date": str(due_date) if due_date else None
    }
