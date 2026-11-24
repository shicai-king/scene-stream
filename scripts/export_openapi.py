from pathlib import Path
import yaml
from longlive.app import create_app

schema = create_app().openapi()
Path("api").mkdir(exist_ok=True)
Path("api/openapi.yaml").write_text(yaml.safe_dump(schema, allow_unicode=True, sort_keys=False))
print("api/openapi.yaml")
