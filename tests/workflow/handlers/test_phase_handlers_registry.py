"""Tests for the PHASE_HANDLERS registry."""

from __future__ import annotations

from agentmux.workflow.handlers import PHASE_HANDLERS


class TestPhaseHandlersRegistry:
    """Tests for the PHASE_HANDLERS registry."""

    def test_all_phases_registered(self) -> None:
        """Test that all expected phases are in the registry."""
        expected_phases = [
            "product_management",
            "planning",
            "designing",
            "implementing",
            "reviewing",
            "fixing",
            "completing",
            "failed",
        ]

        for phase in expected_phases:
            assert phase in PHASE_HANDLERS, f"Phase {phase} not found in registry"

    def test_all_handlers_implement_protocol(self) -> None:
        """Test that all handlers implement the PhaseHandler protocol."""

        for name, handler in PHASE_HANDLERS.items():
            assert hasattr(handler, "enter"), f"{name} missing enter()"
            assert hasattr(handler, "handle_event"), f"{name} missing handle_event()"
            assert callable(handler.enter), f"{name}.enter not callable"
            assert callable(handler.handle_event), f"{name}.handle_event not callable"
