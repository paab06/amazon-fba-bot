#!/usr/bin/env python
"""
FBA Bot CLI - Entry Point

Uso:
  fba-bot crawl --duration 24 --telegram
  fba-bot analyze --asin B07XYZ123
  fba-bot config --categories Electronics,Gaming
  fba-bot test-telegram
  fba-bot status
"""

if __name__ == "__main__":
    from src.cli import cli
    cli()
