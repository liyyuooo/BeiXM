#!/usr/bin/env python3
"""Test Responses API connectivity without sending project data."""

from __future__ import annotations

import json

import ai_client


def main() -> None:
    result = ai_client.responses_json(
        system="You are a JSON-only health-check assistant. Return exactly the requested JSON fields.",
        user_payload={
            "task": "Return whether the Responses API call succeeded.",
            "required_output": {"ok": True, "message": "short status"},
        },
        schema_name="ai_connection_check",
        temperature=0,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
