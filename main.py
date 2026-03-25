from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(
        "src.api.rest.app:app",
        host="0.0.0.0",  # noqa: S104
        port=port,
    )
