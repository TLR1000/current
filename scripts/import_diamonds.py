import os
from pathlib import Path

from app.diamonds import import_diamonds


ROOT = Path(__file__).resolve().parent.parent
database = Path(os.getenv("CURRENT_DB", ROOT / "current.sqlite3"))
source = Path(os.getenv("CURRENT_DIAMONDS_FILE", ROOT / "data" / "diamonds.txt"))
result = import_diamonds(database, source)
print(f"Imported {result['imported_points']} diamonds")
for warning in result["warnings"]:
    print(f"WARNING: {warning}")
