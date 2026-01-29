"""
Tests für das Call Tracker Modul
================================

Testet Metriken-Erfassung, Aggregation und Export-Funktionen.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from call_tracker import CallTracker, ToolCallMetrics, TurnMetrics


class TestTurnMetrics:
    """Tests für TurnMetrics Dataclass."""

    def test_turn_metrics_creation(self):
        """Test: TurnMetrics kann erstellt werden."""
        turn = TurnMetrics(turn_id=1)
        assert turn.turn_id == 1
        assert turn.e2e_latency_ms is None
        assert turn.llm_ttft_ms is None

    def test_turn_metrics_with_values(self):
        """Test: TurnMetrics mit Werten."""
        turn = TurnMetrics(
            turn_id=2,
            e2e_latency_ms=1234.5,
            llm_ttft_ms=321.0,
            tts_ttfb_ms=150.0,
        )
        assert turn.turn_id == 2
        assert turn.e2e_latency_ms == 1234.5
        assert turn.llm_ttft_ms == 321.0


class TestToolCallMetrics:
    """Tests für ToolCallMetrics Dataclass."""

    def test_tool_call_success(self):
        """Test: Tool-Call mit Erfolg."""
        tc = ToolCallMetrics(
            tool_name="get_system_time",
            latency_ms=1.5,
            success=True,
        )
        assert tc.tool_name == "get_system_time"
        assert tc.latency_ms == 1.5
        assert tc.success is True
        assert tc.error_message is None

    def test_tool_call_failure(self):
        """Test: Tool-Call mit Fehler."""
        tc = ToolCallMetrics(
            tool_name="check_availability",
            latency_ms=5000.0,
            success=False,
            error_message="Timeout",
        )
        assert tc.success is False
        assert tc.error_message == "Timeout"


class TestCallTracker:
    """Tests für CallTracker Hauptklasse."""

    def test_initialization(self):
        """Test: CallTracker initialisiert korrekt."""
        tracker = CallTracker(call_id="test-123", room_name="test-room")
        assert tracker.call_id == "test-123"
        assert tracker.room_name == "test-room"
        assert len(tracker.turns) == 0
        assert len(tracker.tool_calls) == 0
        # Cleanup
        CallTracker._current_instance = None

    def test_start_new_turn(self):
        """Test: Neuer Turn wird erstellt."""
        tracker = CallTracker(call_id="test-456")
        turn1 = tracker.start_new_turn()
        assert turn1.turn_id == 1
        turn2 = tracker.start_new_turn()
        assert turn2.turn_id == 2
        assert len(tracker.turns) == 2
        CallTracker._current_instance = None

    def test_record_tool_call(self):
        """Test: Tool-Aufrufe werden erfasst."""
        tracker = CallTracker(call_id="test-789")
        tracker.record_tool_call("get_system_time", 0.001, success=True)
        tracker.record_tool_call("check_availability", 0.250, success=True)
        tracker.record_tool_call("check_availability", 0.500, success=False, error_message="Timeout")

        assert len(tracker.tool_calls) == 3
        assert tracker.tool_calls[0].tool_name == "get_system_time"
        assert tracker.tool_calls[1].latency_ms == 250.0
        assert tracker.tool_calls[2].success is False
        CallTracker._current_instance = None

    def test_e2e_latency_calculation(self):
        """Test: E2E-Latenz wird berechnet."""
        tracker = CallTracker(call_id="test-e2e")
        tracker.start_new_turn()
        
        # Simuliere User spricht fertig
        tracker.mark_user_speech_end()
        
        # Simuliere kleine Verzögerung
        import time
        time.sleep(0.05)  # 50ms
        
        # Agent beginnt zu sprechen
        tracker.mark_first_agent_audio()
        
        # E2E sollte ca. 50ms sein
        assert tracker._current_turn is not None
        assert tracker._current_turn.e2e_latency_ms is not None
        assert 40 < tracker._current_turn.e2e_latency_ms < 100  # Mit Toleranz
        CallTracker._current_instance = None

    def test_aggregated_stats(self):
        """Test: Aggregierte Statistiken werden berechnet."""
        tracker = CallTracker(call_id="test-stats")
        
        # Simuliere mehrere Turns mit verschiedenen Metriken
        turn1 = tracker.start_new_turn()
        turn1.e2e_latency_ms = 800.0
        turn1.llm_ttft_ms = 300.0
        
        turn2 = tracker.start_new_turn()
        turn2.e2e_latency_ms = 1200.0
        turn2.llm_ttft_ms = 400.0
        
        turn3 = tracker.start_new_turn()
        turn3.e2e_latency_ms = 1000.0
        turn3.llm_ttft_ms = 350.0
        
        stats = tracker.get_aggregated_stats()
        
        assert stats["turn_count"] == 3
        assert stats["e2e_latency"]["min"] == 800.0
        assert stats["e2e_latency"]["max"] == 1200.0
        assert stats["e2e_latency"]["avg"] == 1000.0
        assert stats["llm_ttft"]["avg"] == 350.0
        CallTracker._current_instance = None

    def test_tool_stats_aggregation(self):
        """Test: Tool-Statistiken werden gruppiert."""
        tracker = CallTracker(call_id="test-tools")
        
        tracker.record_tool_call("get_system_time", 0.001, success=True)
        tracker.record_tool_call("get_system_time", 0.002, success=True)
        tracker.record_tool_call("check_availability", 0.200, success=True)
        tracker.record_tool_call("check_availability", 0.300, success=False)
        
        stats = tracker.get_aggregated_stats()
        tool_stats = stats["tool_stats"]
        
        assert "get_system_time" in tool_stats
        assert tool_stats["get_system_time"]["count"] == 2
        assert tool_stats["get_system_time"]["success_rate"] == 100.0
        
        assert "check_availability" in tool_stats
        assert tool_stats["check_availability"]["count"] == 2
        assert tool_stats["check_availability"]["success_rate"] == 50.0
        CallTracker._current_instance = None

    def test_get_current_tracker(self):
        """Test: Globale Instanz funktioniert."""
        from call_tracker import get_current_tracker
        
        # Ohne aktiven Tracker
        CallTracker._current_instance = None
        assert get_current_tracker() is None
        
        # Mit aktivem Tracker
        tracker = CallTracker(call_id="test-global")
        assert get_current_tracker() is tracker
        CallTracker._current_instance = None


class TestCallTrackerCSV:
    """Tests für CSV-Export."""

    def test_save_to_csv(self, tmp_path, monkeypatch):
        """Test: CSV-Datei wird erstellt."""
        # Temp-Pfad für CSV
        monkeypatch.setattr("call_tracker.CSV_OUTPUT_DIR", tmp_path)
        
        tracker = CallTracker(call_id="test-csv")
        tracker.start_new_turn()
        tracker.record_tool_call("test_tool", 0.1, success=True)
        
        csv_path = tracker.save_to_csv()
        
        assert csv_path.exists()
        assert csv_path.suffix == ".csv"
        
        # CSV-Inhalt prüfen
        content = csv_path.read_text()
        assert "call_id" in content
        assert "test-csv" in content
        CallTracker._current_instance = None


class TestCallTrackerWebhook:
    """Tests für Webhook-Integration."""

    @pytest.mark.asyncio
    async def test_send_to_webhook_no_url(self, monkeypatch):
        """Test: Webhook überspringt wenn keine URL."""
        monkeypatch.setattr("call_tracker.N8N_KPI_WEBHOOK_URL", "")
        
        tracker = CallTracker(call_id="test-no-url")
        result = await tracker.send_to_webhook()
        assert result is False
        
        CallTracker._current_instance = None

    @pytest.mark.asyncio
    async def test_send_to_webhook_invalid_url(self, monkeypatch):
        """Test: Webhook gibt False bei Connection-Fehler zurück."""
        monkeypatch.setattr("call_tracker.N8N_KPI_WEBHOOK_URL", "http://invalid-host-that-does-not-exist.local/webhook")
        
        tracker = CallTracker(call_id="test-invalid-url")
        result = await tracker.send_to_webhook()
        # Sollte False zurückgeben wegen Connection-Fehler
        assert result is False
        
        CallTracker._current_instance = None

    def test_get_aggregated_stats_includes_webhook_payload(self):
        """Test: Aggregierte Stats enthalten alle Webhook-relevanten Felder."""
        tracker = CallTracker(call_id="test-payload")
        tracker.start_new_turn()
        
        stats = tracker.get_aggregated_stats()
        
        # Prüfe dass alle wichtigen Felder vorhanden sind
        assert "call_id" in stats
        assert "room_name" in stats
        assert "call_duration_seconds" in stats
        assert "turn_count" in stats
        assert "e2e_latency" in stats
        assert "timestamp" in stats
        
        CallTracker._current_instance = None
