"""
Tools MCP organizzati per categoria.

Struttura modulare semplificata:
- invoices.py: Fatture emesse (issued documents)
- payments.py: Pagamenti e incassi
- clients.py: Gestione clienti
- expenses.py: Fatture ricevute (received documents)
- analytics.py: Report e statistiche
- info.py: Informazioni azienda

Ogni modulo espone:
- get_XXX_tools() -> list[Tool]
- get_XXX_handlers() -> dict[str, callable]
"""

from .invoices import get_invoice_tools, get_invoice_handlers
from .payments import get_payment_tools, get_payment_handlers
from .clients import get_client_tools, get_client_handlers
from .expenses import get_expense_tools, get_expense_handlers
from .analytics import get_analytics_tools, get_analytics_handlers
from .info import get_info_tools, get_info_handlers

__all__ = [
    "get_invoice_tools",
    "get_invoice_handlers",
    "get_payment_tools",
    "get_payment_handlers",
    "get_client_tools",
    "get_client_handlers",
    "get_expense_tools",
    "get_expense_handlers",
    "get_analytics_tools",
    "get_analytics_handlers",
    "get_info_tools",
    "get_info_handlers",
]
