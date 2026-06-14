"""Debug: test GrowthBook API connectivity and flag creation with minimal payload.

Run with: uv run python scripts/seed/debug_gb_api.py --api-key YOUR_KEY --project YOUR_PROJECT_ID
"""

from __future__ import annotations

import argparse
import json

import httpx


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Debug GrowthBook API connectivity.")
    parser.add_argument("--api-base", default="https://api.growthbook.io")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--project", required=True)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    client = httpx.Client(
        base_url=args.api_base,
        headers={
            "Authorization": f"Bearer {args.api_key}",
            "Content-Type": "application/json",
        },
        timeout=10.0,
    )

    # Step 0: List available projects and their environments
    print("=== Step 0: Discover projects and environments ===")
    resp = client.get("/api/v2/projects")
    print(f"GET /api/v2/projects status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        projects = data.get("projects", [])
        print(f"Available projects: {len(projects)}")
        for p in projects:
            print(f"  - id={p.get('id')}  name={p.get('name')}")
    else:
        print(f"Body: {resp.text[:500]}")

    resp = client.get("/api/v1/environments")
    print(f"\nGET /api/v1/environments status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        envs = data.get("environments", [])
        print(f"Available environments: {len(envs)}")
        for e in envs:
            print(f"  - id={e.get('id')}  description={e.get('description', '')}")
    else:
        print(f"Body: {resp.text[:500]}")

    # Step 1: List existing features
    print("\n=== Step 1: GET /api/v2/features ===")
    resp = client.get("/api/v2/features")
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        features = data.get("features", [])
        print(f"Existing features: {len(features)}")
        for f in features[:5]:
            print(
                f"  - id={f.get('id')} valueType={f.get('valueType')} defaultValue={f.get('defaultValue')}"
            )
        if len(features) > 5:
            print(f"  ... and {len(features) - 5} more")
    else:
        print(f"Body: {resp.text[:500]}")
        return 1

    # Step 2: Create a minimal boolean flag (no rules, no environments)
    test_id = "test-ping"
    print(f"\n=== Step 2: POST /api/v2/features (minimal, no rules) id={test_id} ===")
    minimal_payload = {
        "id": test_id,
        "owner": "devops@dewflow.com",
        "project": args.project,
        "valueType": "boolean",
        "defaultValue": "false",
    }
    print(f"Payload: {json.dumps(minimal_payload, indent=2)}")
    resp = client.post("/api/v2/features", json=minimal_payload)
    print(f"Status: {resp.status_code}")
    if resp.status_code in (200, 201):
        print("SUCCESS - minimal creation works!")
    else:
        print(f"Body: {resp.text[:500]}")

    # Step 3: Create with environments field
    test_id_2 = "test-ping-env"
    print(f"\n=== Step 3: POST /api/v2/features (with environments) id={test_id_2} ===")
    env_payload = {
        "id": test_id_2,
        "owner": "devops@dewflow.com",
        "project": args.project,
        "valueType": "boolean",
        "defaultValue": "false",
        "environments": {
            "local": {"enabled": True},
            "prod": {"enabled": True},
        },
    }
    print(f"Payload: {json.dumps(env_payload, indent=2)}")
    resp = client.post("/api/v2/features", json=env_payload)
    print(f"Status: {resp.status_code}")
    if resp.status_code in (200, 201):
        print("SUCCESS - environments field accepted!")
    else:
        print(f"Body: {resp.text[:500]}")

    # Step 4: Create with rules
    test_id_3 = "test-ping-rules"
    print(f"\n=== Step 4: POST /api/v2/features (with rules) id={test_id_3} ===")
    rules_payload = {
        "id": test_id_3,
        "owner": "devops@dewflow.com",
        "project": args.project,
        "valueType": "boolean",
        "defaultValue": "false",
        "environments": {
            "local": {"enabled": True},
            "prod": {"enabled": True},
        },
        "rules": [
            {
                "description": "Force on for prod",
                "condition": json.dumps({"env": "prod"}),
                "id": "rule-prod-override",
                "enabled": True,
                "type": "force",
                "value": "true",
                "environments": ["prod"],
            }
        ],
    }
    print(f"Payload: {json.dumps(rules_payload, indent=2)}")
    resp = client.post("/api/v2/features", json=rules_payload)
    print(f"Status: {resp.status_code}")
    if resp.status_code in (200, 201):
        print("SUCCESS - rules field accepted!")
    else:
        print(f"Body: {resp.text[:500]}")

    # Step 5: Clean up test flags
    print("\n=== Step 5: Cleanup test flags ===")
    for tid in [test_id, test_id_2, test_id_3]:
        resp = client.delete(f"/api/v2/features/{tid}")
        print(f"  DELETE {tid}: {resp.status_code}")

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
