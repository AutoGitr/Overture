"""Serve Overture: configure logging once, then hand the app to uvicorn."""

lazy from .cli import main

if __name__ == "__main__":
    main()
