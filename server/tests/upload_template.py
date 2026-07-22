"""
Upload the master template to Azure Blob Storage.

Usage (after setting AZURE_STORAGE_CONNECTION_STRING):
    python server/tests/upload_template.py

This is a manual step — templates are not modified by code.
"""

import asyncio
import os
from pathlib import Path

from azure.storage.blob.aio import BlobServiceClient


TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "template" / "master_resume.tex"
CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER", "resume-archive")
BLOB_PATH = os.getenv("TEMPLATE_BLOB_PATH", "templates/master_resume.tex")


async def upload():
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        print("ERROR: AZURE_STORAGE_CONNECTION_STRING not set")
        print("Set it in .env and run: export $(cat ../.env | xargs)")
        return 1

    if not TEMPLATE_PATH.exists():
        print(f"ERROR: Template not found at {TEMPLATE_PATH}")
        return 1

    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    print(f"Template size: {len(content)} chars, {content.count(chr(10))} lines")

    async with BlobServiceClient.from_connection_string(conn_str) as service:
        async with service.get_blob_client(container=CONTAINER, blob=BLOB_PATH) as client:
            await client.upload_blob(content.encode("utf-8"), overwrite=True)
            print(f"Uploaded to: {CONTAINER}/{BLOB_PATH}")

    print("Done! Template is now the single source of truth in Blob Storage.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(upload()))
