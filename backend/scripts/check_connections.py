"""Connectivity check for all external services configured in .env.

Run from the backend/ directory:  python scripts/check_connections.py

It performs lightweight, low-cost calls (list/head operations) against each
service and prints a PASS/FAIL summary. It never prints secret values.
"""
from __future__ import annotations

import asyncio
import sys

# Ensure the app package is importable when run as a script.
sys.path.insert(0, ".")

from app.config import settings  # noqa: E402


def _mask(value: str | None) -> str:
    if not value:
        return "<empty>"
    return f"{value[:4]}…{value[-4:]} (len {len(value)})"


async def check_mongo() -> tuple[bool, str]:
    try:
        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(settings.mongo_uri, serverSelectionTimeoutMS=3000)
        info = await client.server_info()
        client.close()
        return True, f"MongoDB {info.get('version', '?')} @ {settings.mongo_db_name}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def check_s3() -> tuple[bool, str]:
    try:
        from app.services.s3_service import S3Service

        s3 = S3Service()
        # head_bucket confirms credentials + bucket access without listing data.
        await s3._run(s3._client.head_bucket, Bucket=s3.bucket)
        return True, f"S3 bucket '{s3.bucket}' reachable in {settings.aws_region}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def check_openai() -> tuple[bool, str]:
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        models = await client.models.list()
        names = {m.id for m in models.data}
        has_model = settings.openai_model in names
        note = "model available" if has_model else f"WARNING: {settings.openai_model} not listed"
        return True, f"OpenAI auth OK ({len(names)} models); {note}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def check_recall() -> tuple[bool, str]:
    try:
        import httpx

        from app.services.recall_service import RecallService

        recall = RecallService()
        async with httpx.AsyncClient(timeout=10.0) as http:
            recall._client = http
            # Listing bots is a cheap authenticated GET.
            data = await recall._request("GET", "/bot")
        count = len(data.get("results", [])) if isinstance(data, dict) else "?"
        return True, f"Recall auth OK ({count} bots, base {settings.recall_base_url})"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def main() -> int:
    print("Configured (masked):")
    print(f"  OPENAI_API_KEY      {_mask(settings.openai_api_key)}")
    print(f"  RECALL_API_KEY      {_mask(settings.recall_api_key)}")
    print(f"  AWS_ACCESS_KEY_ID   {_mask(settings.aws_access_key_id)}")
    print(f"  AWS_SECRET          {_mask(settings.aws_secret_access_key)}")
    print(f"  HF_TOKEN            {_mask(settings.hf_token)}")
    print(f"  S3_BUCKET           {settings.s3_bucket} ({settings.aws_region})")
    print()

    checks = {
        "MongoDB": check_mongo(),
        "AWS S3": check_s3(),
        "OpenAI": check_openai(),
        "Recall.ai": check_recall(),
    }
    results = await asyncio.gather(*checks.values())

    print("Connectivity:")
    all_ok = True
    for name, (ok, msg) in zip(checks.keys(), results):
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"  [{status}] {name:10s} {msg}")
    print()
    print("All critical services reachable." if all_ok else "Some services failed — see above.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
