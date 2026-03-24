#!/usr/bin/env python3
"""Backward-compatible entry point for clone-and-run users."""

import sys

from agentmux.pipeline import main


if __name__ == "__main__":
    sys.exit(main())
