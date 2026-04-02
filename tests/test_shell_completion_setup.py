"""Tests for shell completion setup in init command."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from agentmux.pipeline import init_command


class TestDetectShell:
    """Tests for _detect_shell function."""

    @patch.dict("os.environ", {"SHELL": "/bin/bash"}, clear=True)
    def test_detects_bash_shell(self):
        """Test that bash shell is detected correctly."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("# bashrc\n")
            temp_bashrc = Path(f.name)

        with patch.object(Path, "home", return_value=temp_bashrc.parent):
            shell_type, config_path = init_command._detect_shell()
            assert shell_type == "bash"

        temp_bashrc.unlink()

    @patch.dict("os.environ", {"SHELL": "/usr/bin/zsh"}, clear=True)
    def test_detects_zsh_shell(self):
        """Test that zsh shell is detected correctly."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("# zshrc\n")
            temp_zshrc = Path(f.name)

        with patch.object(Path, "home", return_value=temp_zshrc.parent):
            shell_type, config_path = init_command._detect_shell()
            assert shell_type == "zsh"

        temp_zshrc.unlink()

    @patch.dict("os.environ", {"SHELL": "/bin/fish"}, clear=True)
    def test_handles_unknown_shell(self):
        """Test that unknown shells are handled gracefully."""
        shell_type, config_path = init_command._detect_shell()
        assert shell_type == "fish"
        assert config_path.name == ".fishrc"


class TestIsCompletionEnabled:
    """Tests for _is_completion_enabled function."""

    def test_detects_existing_completion(self):
        """Test that existing completion setup is detected."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".rc") as f:
            f.write("# Config\n")
            f.write('eval "$(agentmux completions bash)"\n')
            temp_path = Path(f.name)

        result = init_command._is_completion_enabled(temp_path, "bash")
        assert result is True
        temp_path.unlink()

    def test_returns_false_when_no_completion(self):
        """Test that missing completion setup returns False."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".rc") as f:
            f.write("# Config without agentmux\n")
            temp_path = Path(f.name)

        result = init_command._is_completion_enabled(temp_path, "bash")
        assert result is False
        temp_path.unlink()

    def test_returns_false_for_nonexistent_file(self):
        """Test that non-existent file returns False."""
        temp_path = Path("/nonexistent/path/.bashrc")
        result = init_command._is_completion_enabled(temp_path, "bash")
        assert result is False


class TestEnableCompletions:
    """Tests for _enable_completions function."""

    def test_adds_completion_to_new_file(self):
        """Test that completion is added to a new config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".bashrc"

            result = init_command._enable_completions(config_path, "bash")
            assert result is True

            content = config_path.read_text()
            assert "agentmux completions bash" in content
            assert "# AgentMux Shell Completions" in content

    def test_appends_to_existing_file(self):
        """Test that completion is appended to existing config."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".rc") as f:
            f.write("# Existing config\n")
            f.write("export PATH=/usr/local/bin:$PATH\n")
            temp_path = Path(f.name)

        result = init_command._enable_completions(temp_path, "bash")
        assert result is True

        content = temp_path.read_text()
        assert "Existing config" in content
        assert "agentmux completions bash" in content
        temp_path.unlink()


class TestPromptShellCompletions:
    """Tests for prompt_shell_completions function."""

    @patch("agentmux.pipeline.init_command._detect_shell")
    @patch("agentmux.pipeline.init_command._is_completion_enabled")
    @patch("agentmux.pipeline.init_command._confirm")
    @patch("agentmux.pipeline.init_command._enable_completions")
    def test_prompts_user_and_enables(
        self, mock_enable, mock_confirm, mock_is_enabled, mock_detect
    ):
        """Test that user is prompted and completions are enabled."""
        mock_detect.return_value = ("bash", Path("/home/user/.bashrc"))
        mock_is_enabled.return_value = False
        mock_confirm.return_value = True
        mock_enable.return_value = True

        console = MagicMock()
        result = init_command.prompt_shell_completions(console)

        assert result == (True, "enabled")
        mock_confirm.assert_called_once()
        mock_enable.assert_called_once()

    @patch("agentmux.pipeline.init_command._detect_shell")
    @patch("agentmux.pipeline.init_command._is_completion_enabled")
    def test_skips_when_already_enabled(self, mock_is_enabled, mock_detect):
        """Test that already enabled completions are skipped."""
        mock_detect.return_value = ("bash", Path("/home/user/.bashrc"))
        mock_is_enabled.return_value = True

        console = MagicMock()
        result = init_command.prompt_shell_completions(console)

        assert result == (True, "already-enabled")

    @patch("agentmux.pipeline.init_command._detect_shell")
    def test_handles_unsupported_shell(self, mock_detect):
        """Test that unsupported shells are handled."""
        mock_detect.return_value = ("fish", Path("/home/user/.config/fish/config.fish"))

        console = MagicMock()
        result = init_command.prompt_shell_completions(console)

        assert result == (False, "unsupported-shell")

    @patch("agentmux.pipeline.init_command._detect_shell")
    @patch("agentmux.pipeline.init_command._is_completion_enabled")
    @patch("agentmux.pipeline.init_command._confirm")
    def test_user_can_skip(self, mock_confirm, mock_is_enabled, mock_detect):
        """Test that user can skip enabling completions."""
        mock_detect.return_value = ("bash", Path("/home/user/.bashrc"))
        mock_is_enabled.return_value = False
        mock_confirm.return_value = False

        console = MagicMock()
        result = init_command.prompt_shell_completions(console)

        assert result == (False, "skipped")
