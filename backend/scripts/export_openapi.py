"""Write the OpenAPI schema to a file so the frontend can generate a typed client."""

import json
import sys
from pathlib import Path

from app.main import app

out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
out.write_text(json.dumps(app.openapi(), indent=2) + "\n")
print(f"Wrote {out}")
