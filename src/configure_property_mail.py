from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pydantic import ValidationError

from property_mail_service import InfraiClient, InfraiError, PropertyMailRequest, configure_property_mail


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure property-management MX records")
    parser.add_argument("request", type=Path, help="JSON request file")
    args = parser.parse_args()

    api_key = os.environ.get("INFRAI_API_KEY")
    if not api_key:
        parser.error("INFRAI_API_KEY is required")

    try:
        request = PropertyMailRequest.model_validate_json(args.request.read_text())
    except (OSError, ValidationError) as exc:
        parser.error(str(exc))

    client = InfraiClient(api_key)
    try:
        result = configure_property_mail(client, request)
        print(result.model_dump_json(indent=2))
        return 0
    except InfraiError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "detail": exc.detail}))
        return 2 if 400 <= exc.status_code < 500 else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
