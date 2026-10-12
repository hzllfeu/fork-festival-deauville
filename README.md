Deauville Festival du Rire

Application de gestion du programme du festival : artistes, lieux, spectacles et ateliers.

Installation :
uv sync

Lancer le site :
uv run main.py serve --port 9000

Commandes :
uv run main.py day 2027-06-11
uv run main.py artists
uv run main.py now --at 2027-06-11T21:00

Tests :
uv run pytest

L'API est dans api.py. Le site public est dans web/public et l'administration dans web/admin.
