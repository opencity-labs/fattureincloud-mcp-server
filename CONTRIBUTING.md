# Come Contribuire

Grazie per il tuo interesse nel migliorare FattureInCloud MCP Server!

## Segnalare Bug o Proporre Funzionalita'

Apri una [Issue](https://github.com/maxmost-hestro/fattureincloud-mcp-server/issues) descrivendo:
- Cosa hai osservato (o cosa vorresti)
- Come riprodurre il problema (se e' un bug)
- Versione Python e sistema operativo

## Contribuire con Codice

1. **Fork** il repository
2. Crea un branch per la tua modifica:
   ```bash
   git checkout -b feature/nome-feature
   ```
3. Fai le tue modifiche seguendo le convenzioni del progetto
4. Testa che il server si avvii correttamente:
   ```bash
   python server.py
   ```
5. Committa con un messaggio chiaro:
   ```bash
   git commit -m "feat: descrizione della modifica"
   ```
6. Pusha e apri una **Pull Request**

## Convenzioni

### Commit Messages

Usa [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — Nuova funzionalita'
- `fix:` — Correzione bug
- `docs:` — Documentazione
- `refactor:` — Refactoring senza cambio di comportamento
- `chore:` — Manutenzione, dipendenze

### Stile Codice

- Python 3.11+
- Segui lo stile esistente nel progetto
- Docstring per le funzioni pubbliche
- Type hints dove possibile

### Struttura Tools

Ogni nuovo tool va in un file della cartella `src/tools/` e deve:
1. Essere registrato in `server.py`
2. Restituire una stringa formattata leggibile
3. Gestire errori API con messaggi chiari
4. Implementare paginazione se l'API lo richiede

## Variabili d'Ambiente

Non committare mai file `.env` con credenziali reali. Aggiorna `.env.example` se aggiungi nuove variabili.

## Domande?

Contatta [massimo.mostallino@hestro.it](mailto:massimo.mostallino@hestro.it)
