#!/usr/bin/env python3
"""Entry point for Pi Assistant."""

import uvicorn
from backend.config import get_settings


def main():
    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
