"""
Tools per informazioni aziendali.
"""

from mcp.types import Tool, TextContent
from fattureincloud_python_sdk.api import user_api

from ..config import get_api_client


async def handle_get_company_info(arguments: dict) -> list[TextContent]:
    """Informazioni azienda."""
    with get_api_client() as api_client:
        api = user_api.UserApi(api_client)

        try:
            response = api.list_user_companies()

            if not response.data or not response.data.companies:
                return [TextContent(type="text", text="Nessuna azienda trovata")]

            companies = response.data.companies
            output = f"Trovate {len(companies)} aziende:\n\n"

            for company in companies:
                output += f"{'=' * 40}\n"
                output += f"Azienda: {company.name}\n"
                output += f"Company ID: {company.id}\n"

                if company.type:
                    output += f"Tipo: {company.type}\n"

                if company.tax_code:
                    output += f"Codice Fiscale: {company.tax_code}\n"

                if company.connection_id:
                    output += f"Connection ID: {company.connection_id}\n"

                if hasattr(company, 'access_token') and company.access_token:
                    output += f"Access Token: {company.access_token[:20]}...\n"

                if hasattr(company, 'controlled_companies') and company.controlled_companies:
                    output += f"Aziende controllate: {len(company.controlled_companies)}\n"

                output += "\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"Errore: {str(e)}")]


def get_info_tools():
    """Restituisce la lista di tool per informazioni aziendali."""
    return [
        Tool(
            name="get_company_info",
            description="Informazioni sulle aziende associate all'account",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
    ]


def get_info_handlers():
    """Restituisce il dizionario di handler per informazioni aziendali."""
    return {
        "get_company_info": handle_get_company_info,
    }
