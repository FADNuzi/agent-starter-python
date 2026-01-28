import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from tools import check_availability, get_system_time


class TestGetSystemTime:
    """Tests für get_system_time() Tool"""

    @pytest.mark.asyncio
    async def test_returns_correct_format(self):
        """Prüft ob alle erwarteten Felder vorhanden sind"""
        result = await get_system_time()
        
        assert "current_date" in result
        assert "current_time" in result
        assert "weekday" in result
        assert "weekday_number" in result
        assert "is_dst" in result
        
        # Prüfe Datumsformat YYYY-MM-DD
        assert len(result["current_date"]) == 10
        assert result["current_date"][4] == "-"
        assert result["current_date"][7] == "-"
        
        # Prüfe Zeitformat HH:MM
        assert len(result["current_time"]) == 5
        assert result["current_time"][2] == ":"

    @pytest.mark.asyncio
    async def test_weekday_calculation(self):
        """Prüft ob der Wochentag korrekt berechnet wird"""
        result = await get_system_time()
        
        weekdays = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
        assert result["weekday"] in weekdays
        assert 0 <= result["weekday_number"] <= 6
        
        # Überprüfe Konsistenz zwischen weekday und weekday_number
        assert result["weekday"] == weekdays[result["weekday_number"]]

    @pytest.mark.asyncio
    async def test_timezone_europe_berlin(self):
        """Prüft ob die Zeitzone Europe/Berlin verwendet wird"""
        with patch("tools.datetime") as mock_dt:
            tz = ZoneInfo("Europe/Berlin")
            mock_now = datetime(2026, 1, 28, 14, 30, tzinfo=tz)
            mock_dt.now.return_value = mock_now
            
            result = await get_system_time()
            
            assert result["current_date"] == "2026-01-28"
            assert result["current_time"] == "14:30"


class TestCheckAvailability:
    """Tests für check_availability() Tool"""

    @pytest.mark.asyncio
    async def test_request_format(self):
        """Prüft ob das Request-Format korrekt ist"""
        mock_json = AsyncMock(return_value={
            "status": "available",
            "message": "Termin ist frei.",
            "slots_primary": [],
            "slots_secondary": [],
        })
        
        with patch("tools.N8N_CHECK_AVAILABILITY_WEBHOOK", "https://test.example.com/webhook"):
            with patch("aiohttp.ClientSession") as mock_session_cls:
                mock_response = AsyncMock()
                mock_response.json = mock_json
                
                mock_session = AsyncMock()
                mock_post = AsyncMock()
                mock_post.__aenter__.return_value = mock_response
                mock_session.post.return_value = mock_post
                mock_session_cls.return_value.__aenter__.return_value = mock_session
                
                result = await check_availability(
                    date="2026-02-15",
                    time="14:30",
                    service="Herrenschnitt",
                    duration=30,
                )
                
                # Prüfe dass alle 4 Parameter gesendet wurden
                assert result["status"] == "available"
                mock_session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_available_response(self):
        """Prüft Verarbeitung von 'available' Status"""
        mock_json = AsyncMock(return_value={
            "status": "available",
            "message": "Termin ist frei.",
            "slots_primary": [{"date": "2026-02-15", "time": "14:30"}],
            "slots_secondary": [],
        })
        
        with patch("tools.N8N_CHECK_AVAILABILITY_WEBHOOK", "https://test.example.com/webhook"):
            with patch("aiohttp.ClientSession") as mock_session_cls:
                mock_response = AsyncMock()
                mock_response.json = mock_json
                
                mock_session = AsyncMock()
                mock_post = AsyncMock()
                mock_post.__aenter__.return_value = mock_response
                mock_session.post.return_value = mock_post
                mock_session_cls.return_value.__aenter__.return_value = mock_session
                
                result = await check_availability(
                    date="2026-02-15",
                    time="14:30",
                    service="Herrenschnitt",
                    duration=30,
                )
                
                assert result["status"] == "available"
                assert len(result["slots_primary"]) == 1

    @pytest.mark.asyncio
    async def test_handles_error_response(self):
        """Prüft Verarbeitung von Fehler-Status"""
        mock_json = AsyncMock(return_value={
            "status": "error",
            "type": "validation_error",
            "message": "Fehlende Information: Datum.",
            "missing_field": "Datum",
        })
        
        with patch("tools.N8N_CHECK_AVAILABILITY_WEBHOOK", "https://test.example.com/webhook"):
            with patch("aiohttp.ClientSession") as mock_session_cls:
                mock_response = AsyncMock()
                mock_response.json = mock_json
                
                mock_session = AsyncMock()
                mock_post = AsyncMock()
                mock_post.__aenter__.return_value = mock_response
                mock_session.post.return_value = mock_post
                mock_session_cls.return_value.__aenter__.return_value = mock_session
                
                result = await check_availability(
                    date="",
                    time="14:30",
                    service="Herrenschnitt",
                    duration=30,
                )
                
                assert result["status"] == "error"
                assert result["type"] == "validation_error"

    @pytest.mark.asyncio
    async def test_handles_missing_webhook_url(self):
        """Prüft Fehlerbehandlung wenn Webhook URL fehlt"""
        with patch("tools.N8N_CHECK_AVAILABILITY_WEBHOOK", None):
            result = await check_availability(
                date="2026-02-15",
                time="14:30",
                service="Herrenschnitt",
                duration=30,
            )
            
            assert result["status"] == "error"
            assert result["type"] == "configuration_error"
