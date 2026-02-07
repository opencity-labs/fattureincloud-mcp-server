"""
Configurazione centralizzata del server MCP.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import fattureincloud_python_sdk as fic

# Carica .env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Configurazione API
ACCESS_TOKEN = os.getenv("FIC_ACCESS_TOKEN")
COMPANY_ID = int(os.getenv("FIC_COMPANY_ID", 0))
COMPANY_NAME = os.getenv("FIC_COMPANY_NAME", "N/A")

if not ACCESS_TOKEN or not COMPANY_ID:
    raise ValueError(
        "Configurazione mancante! Verifica .env con FIC_ACCESS_TOKEN e FIC_COMPANY_ID"
    )

# Setup SDK FattureInCloud
configuration = fic.Configuration(host="https://api-v2.fattureincloud.it")
configuration.access_token = ACCESS_TOKEN


def get_api_client():
    """Crea un API client configurato."""
    return fic.ApiClient(configuration)
