from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tmux import send_prompt


class TmuxPromptReferencesTests(unittest.TestCase):
    def test_send_prompt_sends_reference_message_not_full_prompt_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            prompt_file = Path(td) / "coder_prompt.md"
            prompt_file.write_text("line 1\\nline 2\\n", encoding="utf-8")
            sent: list[str] = []

            with patch("src.tmux.tmux_pane_exists", return_value=True), patch(
                "src.tmux.show_agent_pane", return_value=None
            ), patch("src.tmux.send_text", side_effect=lambda _pane, text: sent.append(text)):
                send_prompt("%1", prompt_file, session_name="session-x")

            self.assertEqual(1, len(sent))
            self.assertEqual(
                f"Read and follow the instructions in {prompt_file.resolve()}",
                sent[0],
            )
            self.assertNotIn("line 1", sent[0])


if __name__ == "__main__":
    unittest.main()
