#!/usr/bin/env python3
"""CLI entry point for agentmux pipeline."""

from __future__ import annotations

from .application import PipelineApplication
from .cli import DEFAULT_CONFIG_HINT, build_parser, main

__all__ = ["main", "DEFAULT_CONFIG_HINT", "PipelineApplication", "build_parser"]
