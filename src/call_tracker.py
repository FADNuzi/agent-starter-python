"""
Call Tracker - KPI Measurement System für Voice Bot
====================================================

Erfasst und aggregiert Metriken für:
- E2E Voice-to-Voice Latenz
- STT, LLM, TTS Pipeline-Metriken
- Tool-Aufrufe
- Anruf-Statistiken

Ausgabe: Terminal (Rich), CSV-Datei, n8n-Webhook
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import aiohttp
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from livekit.agents.metrics import (
        AgentMetrics,
        EOUMetrics,
        LLMMetrics,
        STTMetrics,
        TTSMetrics,
        VADMetrics,
    )

logger = logging.getLogger("friseur-agent.tracker")
console = Console()

# Konfiguration
N8N_KPI_WEBHOOK_URL = os.getenv(
    "N8N_KPI_WEBHOOK_URL",
    "https://staging.ki-prozesshelden.de/webhook/35d7c183-92b5-4d6b-9c2d-69134bbba6be",
)
CSV_OUTPUT_DIR = Path("kpi_logs")
TIMEZONE = ZoneInfo("Europe/Berlin")


@dataclass
class ToolCallMetrics:
    """Metriken für einen einzelnen Tool-Aufruf."""

    tool_name: str
    latency_ms: float
    success: bool
    timestamp: float = field(default_factory=time.time)
    error_message: str | None = None


@dataclass
class TurnMetrics:
    """Metriken für einen einzelnen Turn (User spricht → Agent antwortet)."""

    turn_id: int
    user_speech_end_ts: float | None = None
    first_agent_audio_ts: float | None = None
    e2e_latency_ms: float | None = None

    # Pipeline-Metriken (können None sein wenn noch nicht erfasst)
    stt_duration_ms: float | None = None
    stt_audio_duration_ms: float | None = None

    llm_ttft_ms: float | None = None
    llm_duration_ms: float | None = None
    llm_prompt_tokens: int | None = None
    llm_completion_tokens: int | None = None
    llm_tokens_per_second: float | None = None

    tts_ttfb_ms: float | None = None
    tts_duration_ms: float | None = None
    tts_audio_duration_ms: float | None = None
    tts_characters: int | None = None

    # EOU-Metriken
    eou_delay_ms: float | None = None
    transcription_delay_ms: float | None = None


class CallTracker:
    """
    Hauptklasse für KPI-Tracking pro Anruf.

    Erfasst Metriken während des Anrufs und gibt am Ende eine
    Zusammenfassung aus (Terminal + CSV + Webhook).
    """

    # Globale Instanz für Tool-Zugriff
    _current_instance: CallTracker | None = None

    def __init__(self, call_id: str | None = None, room_name: str | None = None):
        self.call_id = call_id or f"call_{int(time.time())}"
        self.room_name = room_name or "unknown"
        self.start_time = time.time()
        self.end_time: float | None = None

        self.turns: list[TurnMetrics] = []
        self.tool_calls: list[ToolCallMetrics] = []

        self._current_turn: TurnMetrics | None = None
        self._turn_counter = 0

        # Für E2E-Berechnung
        self._last_user_speech_end: float | None = None

        # Setze globale Instanz
        CallTracker._current_instance = self

        logger.info(f"CallTracker initialized: {self.call_id}")

    # =========================================================================
    # TURN MANAGEMENT
    # =========================================================================

    def start_new_turn(self) -> TurnMetrics:
        """Startet einen neuen Turn."""
        self._turn_counter += 1
        self._current_turn = TurnMetrics(turn_id=self._turn_counter)
        self.turns.append(self._current_turn)
        logger.debug(f"Turn {self._turn_counter} started")
        return self._current_turn

    def mark_user_speech_end(self) -> None:
        """Markiert das Ende der User-Sprache (für E2E-Berechnung)."""
        # Falls der aktuelle Turn bereits eine E2E-Messung hat, starten wir einen neuen,
        # da wir offenbar den Start-Event verpasst haben.
        if self._current_turn and self._current_turn.e2e_latency_ms is not None:
            logger.warning("Turn start missed? Auto-starting new turn.")
            self.start_new_turn()

        self._last_user_speech_end = time.time()
        if self._current_turn:
            self._current_turn.user_speech_end_ts = self._last_user_speech_end
        logger.debug("User speech end marked")

    def mark_first_agent_audio(self) -> None:
        """Markiert den ersten Agent-Audio-Frame (für E2E-Berechnung)."""
        now = time.time()
        if self._current_turn and self._last_user_speech_end:
            self._current_turn.first_agent_audio_ts = now
            self._current_turn.e2e_latency_ms = (
                now - self._last_user_speech_end
            ) * 1000
            logger.debug(f"E2E Latency: {self._current_turn.e2e_latency_ms:.1f}ms")

    # =========================================================================
    # METRICS RECORDING
    # =========================================================================

    def record_metrics(self, metrics: AgentMetrics) -> None:
        """
        Hauptmethode: Nimmt AgentMetrics entgegen und routet zum richtigen Handler.
        """
        metrics_type = metrics.type

        if metrics_type == "stt_metrics":
            self._record_stt(metrics)  # type: ignore
        elif metrics_type == "llm_metrics":
            self._record_llm(metrics)  # type: ignore
        elif metrics_type == "tts_metrics":
            self._record_tts(metrics)  # type: ignore
        elif metrics_type == "eou_metrics":
            self._record_eou(metrics)  # type: ignore
        elif metrics_type == "vad_metrics":
            self._record_vad(metrics)  # type: ignore

        # Verbose-Ausgabe im Terminal
        self._print_turn_detail(metrics)

    def _record_stt(self, metrics: STTMetrics) -> None:
        """Erfasst STT-Metriken."""
        # STT deutet auf neuen User-Input hin.
        # Wenn der aktuelle Turn schon "benutzt" wurde (hat E2E oder TTS), starten wir neu.
        if not self._current_turn or (self._current_turn.e2e_latency_ms is not None):
            self.start_new_turn()

        if self._current_turn:
            # Bei Streaming-STT ist duration=0, daher audio_duration nutzen
            self._current_turn.stt_duration_ms = metrics.audio_duration * 1000
            self._current_turn.stt_audio_duration_ms = metrics.audio_duration * 1000

    def _record_llm(self, metrics: LLMMetrics) -> None:
        """Erfasst LLM-Metriken."""
        if not self._current_turn:
            self.start_new_turn()

        if self._current_turn:
            self._current_turn.llm_ttft_ms = metrics.ttft * 1000
            self._current_turn.llm_duration_ms = metrics.duration * 1000
            self._current_turn.llm_prompt_tokens = metrics.prompt_tokens
            self._current_turn.llm_completion_tokens = metrics.completion_tokens
            self._current_turn.llm_tokens_per_second = metrics.tokens_per_second

    def _record_tts(self, metrics: TTSMetrics) -> None:
        """Erfasst TTS-Metriken."""
        if not self._current_turn:
            self.start_new_turn()

        if self._current_turn:
            self._current_turn.tts_ttfb_ms = metrics.ttfb * 1000
            self._current_turn.tts_duration_ms = metrics.duration * 1000
            self._current_turn.tts_audio_duration_ms = metrics.audio_duration * 1000
            self._current_turn.tts_characters = metrics.characters_count

            # E2E BERECHNUNG via TTS Metrics (Fallback/Primär da Events fehlen)
            if self._current_turn.e2e_latency_ms is None and self._last_user_speech_end:
                # TTS Timestamp = Request Start. Audio Start = Timestamp + TTFB
                approx_audio_start = metrics.timestamp + metrics.ttfb
                latency_ms = (approx_audio_start - self._last_user_speech_end) * 1000

                # Plausibilitätscheck (1ms - 10s)
                if 1 < latency_ms < 10000:
                    self._current_turn.e2e_latency_ms = latency_ms
                    logger.info(f"E2E calculated via TTS Metrics: {latency_ms:.1f}ms")

    def _record_eou(self, metrics: EOUMetrics) -> None:
        """Erfasst EOU-Metriken (End of Utterance)."""
        if self._current_turn:
            self._current_turn.eou_delay_ms = metrics.end_of_utterance_delay * 1000
            self._current_turn.transcription_delay_ms = (
                metrics.transcription_delay * 1000
            )

        # EOU (End of Utterance) ist der zuverlässigste Marker für "User stopped speaking"
        # Wir nutzen den Timestamp aus der Metrik für maximale Präzision
        # EOU Event Time ≈ Timestamp + Delay
        eou_time = metrics.timestamp + metrics.end_of_utterance_delay
        self._last_user_speech_end = eou_time

        if self._current_turn:
            self._current_turn.user_speech_end_ts = eou_time
            logger.debug(f"User speech end marked via EOU (ts={eou_time:.3f})")

    def _record_vad(self, metrics: VADMetrics) -> None:
        """Erfasst VAD-Metriken (aktuell nur für Logging)."""
        # VADMetrics hat: type, label, timestamp, idle_time
        if hasattr(metrics, "idle_time"):
            logger.debug(f"VAD: idle={metrics.idle_time:.3f}s")
        else:
            logger.debug(f"VAD metrics received")

    # =========================================================================
    # TOOL CALL TRACKING
    # =========================================================================

    def record_tool_call(
        self,
        tool_name: str,
        latency_seconds: float,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """Erfasst einen Tool-Aufruf."""
        tool_metrics = ToolCallMetrics(
            tool_name=tool_name,
            latency_ms=latency_seconds * 1000,
            success=success,
            error_message=error_message,
        )
        self.tool_calls.append(tool_metrics)
        logger.debug(
            f"Tool '{tool_name}': {tool_metrics.latency_ms:.1f}ms, success={success}"
        )

    # =========================================================================
    # VERBOSE TERMINAL OUTPUT
    # =========================================================================

    def _print_turn_detail(self, metrics: AgentMetrics) -> None:
        """Gibt Detail-Infos für jeden Metrics-Event aus (Verbose Mode)."""
        timestamp = datetime.now(TIMEZONE).strftime("%H:%M:%S.%f")[:-3]
        metrics_type = metrics.type.upper().replace("_METRICS", "")

        # Farbcodierung nach Typ
        colors = {
            "STT": "cyan",
            "LLM": "green",
            "TTS": "yellow",
            "EOU": "magenta",
            "VAD": "blue",
        }
        color = colors.get(metrics_type, "white")

        # Detailausgabe je nach Typ
        if metrics_type == "STT":
            # Bei Streaming-STT ist metrics.duration=0, daher audio_duration zeigen
            detail = f"audio={metrics.audio_duration * 1000:.0f}ms (streamed={metrics.streamed})"  # type: ignore
        elif metrics_type == "LLM":
            detail = f"TTFT={metrics.ttft * 1000:.0f}ms tokens={metrics.completion_tokens} ({metrics.tokens_per_second:.0f}/s)"  # type: ignore
        elif metrics_type == "TTS":
            detail = (
                f"TTFB={metrics.ttfb * 1000:.0f}ms chars={metrics.characters_count}"  # type: ignore
            )
        elif metrics_type == "EOU":
            detail = f"delay={metrics.end_of_utterance_delay * 1000:.0f}ms"  # type: ignore
        else:
            detail = ""

        console.print(
            f"[dim]{timestamp}[/dim] [{color}]{metrics_type:4}[/{color}] {detail}"
        )

    # =========================================================================
    # AGGREGATION
    # =========================================================================

    def _calc_stats(self, values: list[float | None]) -> dict[str, float]:
        """Berechnet Min/Max/Avg für eine Liste von Werten."""
        valid = [v for v in values if v is not None]
        if not valid:
            return {"min": 0, "max": 0, "avg": 0, "count": 0}
        return {
            "min": min(valid),
            "max": max(valid),
            "avg": sum(valid) / len(valid),
            "count": len(valid),
        }

    def get_aggregated_stats(self) -> dict:
        """Berechnet aggregierte Statistiken für den gesamten Anruf."""
        call_duration = (self.end_time or time.time()) - self.start_time

        # E2E Latenz
        e2e_values = [t.e2e_latency_ms for t in self.turns]
        e2e_stats = self._calc_stats(e2e_values)

        # Pipeline-Metriken
        stt_durations = [t.stt_duration_ms for t in self.turns]
        llm_ttfts = [t.llm_ttft_ms for t in self.turns]
        llm_durations = [t.llm_duration_ms for t in self.turns]
        tts_ttfbs = [t.tts_ttfb_ms for t in self.turns]
        tts_durations = [t.tts_duration_ms for t in self.turns]

        # Tool-Statistiken gruppiert nach Name
        tool_stats: dict[str, dict] = {}
        for tc in self.tool_calls:
            if tc.tool_name not in tool_stats:
                tool_stats[tc.tool_name] = {
                    "latencies": [],
                    "successes": 0,
                    "failures": 0,
                }
            tool_stats[tc.tool_name]["latencies"].append(tc.latency_ms)
            if tc.success:
                tool_stats[tc.tool_name]["successes"] += 1
            else:
                tool_stats[tc.tool_name]["failures"] += 1

        for name, stats in tool_stats.items():
            stats["count"] = len(stats["latencies"])
            stats["avg_latency_ms"] = (
                sum(stats["latencies"]) / len(stats["latencies"])
                if stats["latencies"]
                else 0
            )
            stats["success_rate"] = (
                stats["successes"] / stats["count"] * 100 if stats["count"] > 0 else 0
            )

        return {
            "call_id": self.call_id,
            "room_name": self.room_name,
            "call_duration_seconds": call_duration,
            "turn_count": len(self.turns),
            "tool_call_count": len(self.tool_calls),
            "e2e_latency": e2e_stats,
            "stt_duration": self._calc_stats(stt_durations),
            "llm_ttft": self._calc_stats(llm_ttfts),
            "llm_duration": self._calc_stats(llm_durations),
            "tts_ttfb": self._calc_stats(tts_ttfbs),
            "tts_duration": self._calc_stats(tts_durations),
            "tool_stats": tool_stats,
            "timestamp": datetime.now(TIMEZONE).isoformat(),
        }

    # =========================================================================
    # OUTPUT: TERMINAL SUMMARY
    # =========================================================================

    def print_summary(self) -> None:
        """Gibt eine formatierte Zusammenfassung im Terminal aus."""
        self.end_time = time.time()
        stats = self.get_aggregated_stats()

        # Haupttabelle
        table = Table(
            title="📊 CALL SUMMARY - Haarparadies",
            show_header=True,
            header_style="bold cyan",
            border_style="bright_blue",
        )

        table.add_column("Metrik", style="dim")
        table.add_column("Min", justify="right")
        table.add_column("Avg", justify="right", style="bold")
        table.add_column("Max", justify="right")

        # E2E Latenz
        e2e = stats["e2e_latency"]
        if e2e["count"] > 0:
            table.add_row(
                "🎯 E2E Latency",
                f"{e2e['min']:.0f}ms",
                f"{e2e['avg']:.0f}ms",
                f"{e2e['max']:.0f}ms",
            )

        # STT
        stt = stats["stt_duration"]
        if stt["count"] > 0:
            table.add_row(
                "🎤 STT Audio",
                f"{stt['min']:.0f}ms",
                f"{stt['avg']:.0f}ms",
                f"{stt['max']:.0f}ms",
            )

        # LLM TTFT
        llm_ttft = stats["llm_ttft"]
        if llm_ttft["count"] > 0:
            table.add_row(
                "🧠 LLM TTFT",
                f"{llm_ttft['min']:.0f}ms",
                f"{llm_ttft['avg']:.0f}ms",
                f"{llm_ttft['max']:.0f}ms",
            )

        # LLM Duration
        llm_dur = stats["llm_duration"]
        if llm_dur["count"] > 0:
            table.add_row(
                "🧠 LLM Duration",
                f"{llm_dur['min']:.0f}ms",
                f"{llm_dur['avg']:.0f}ms",
                f"{llm_dur['max']:.0f}ms",
            )

        # TTS TTFB
        tts_ttfb = stats["tts_ttfb"]
        if tts_ttfb["count"] > 0:
            table.add_row(
                "🔊 TTS TTFB",
                f"{tts_ttfb['min']:.0f}ms",
                f"{tts_ttfb['avg']:.0f}ms",
                f"{tts_ttfb['max']:.0f}ms",
            )

        # TTS Duration
        tts_dur = stats["tts_duration"]
        if tts_dur["count"] > 0:
            table.add_row(
                "🔊 TTS Duration",
                f"{tts_dur['min']:.0f}ms",
                f"{tts_dur['avg']:.0f}ms",
                f"{tts_dur['max']:.0f}ms",
            )

        # Header-Info
        duration_str = f"{stats['call_duration_seconds']:.1f}s"
        header = f"Call ID: {self.call_id}\nDuration: {duration_str} | Turns: {stats['turn_count']} | Tools: {stats['tool_call_count']}"

        console.print("\n")
        console.print(Panel(header, title="📞 Call Info", border_style="green"))
        console.print(table)

        # Tool-Tabelle (wenn Tools aufgerufen wurden)
        if stats["tool_stats"]:
            tool_table = Table(
                title="🔧 Tool Calls",
                show_header=True,
                header_style="bold yellow",
                border_style="yellow",
            )
            tool_table.add_column("Tool", style="dim")
            tool_table.add_column("Count", justify="right")
            tool_table.add_column("Avg Latency", justify="right")
            tool_table.add_column("Success Rate", justify="right")

            for name, ts in stats["tool_stats"].items():
                success_style = "green" if ts["success_rate"] == 100 else "red"
                tool_table.add_row(
                    name,
                    str(ts["count"]),
                    f"{ts['avg_latency_ms']:.0f}ms",
                    f"[{success_style}]{ts['success_rate']:.0f}%[/{success_style}]",
                )

            console.print(tool_table)

        console.print("\n")

    # =========================================================================
    # OUTPUT: CSV
    # =========================================================================

    def save_to_csv(self) -> Path:
        """Speichert die Metriken in einer CSV-Datei."""
        CSV_OUTPUT_DIR.mkdir(exist_ok=True)

        timestamp = datetime.now(TIMEZONE).strftime("%Y%m%d_%H%M%S")
        filepath = CSV_OUTPUT_DIR / f"call_{timestamp}_{self.call_id[:8]}.csv"

        stats = self.get_aggregated_stats()

        # Flache Struktur für CSV
        row = {
            "timestamp": stats["timestamp"],
            "call_id": stats["call_id"],
            "room_name": stats["room_name"],
            "duration_s": f"{stats['call_duration_seconds']:.2f}",
            "turn_count": stats["turn_count"],
            "tool_count": stats["tool_call_count"],
            "e2e_min_ms": f"{stats['e2e_latency']['min']:.0f}",
            "e2e_avg_ms": f"{stats['e2e_latency']['avg']:.0f}",
            "e2e_max_ms": f"{stats['e2e_latency']['max']:.0f}",
            "stt_avg_ms": f"{stats['stt_duration']['avg']:.0f}",
            "llm_ttft_avg_ms": f"{stats['llm_ttft']['avg']:.0f}",
            "llm_dur_avg_ms": f"{stats['llm_duration']['avg']:.0f}",
            "tts_ttfb_avg_ms": f"{stats['tts_ttfb']['avg']:.0f}",
            "tts_dur_avg_ms": f"{stats['tts_duration']['avg']:.0f}",
        }

        # CSV schreiben
        file_exists = filepath.exists()
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

        logger.info(f"KPI saved to CSV: {filepath}")
        return filepath

    # =========================================================================
    # OUTPUT: WEBHOOK
    # =========================================================================

    async def send_to_webhook(self) -> bool:
        """Sendet die Metriken an den n8n-Webhook."""
        if not N8N_KPI_WEBHOOK_URL:
            logger.warning("N8N_KPI_WEBHOOK_URL not configured, skipping webhook")
            return False

        stats = self.get_aggregated_stats()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    N8N_KPI_WEBHOOK_URL,
                    json=stats,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        logger.info(f"KPI sent to webhook successfully")
                        return True
                    else:
                        logger.error(f"Webhook returned status {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Failed to send KPI to webhook: {e}")
            return False

    # =========================================================================
    # CLEANUP
    # =========================================================================

    async def finalize(self) -> None:
        """Finalisiert den Tracker: Summary, CSV, Webhook."""
        self.end_time = time.time()
        self.print_summary()
        self.save_to_csv()
        await self.send_to_webhook()

        # Globale Instanz zurücksetzen
        if CallTracker._current_instance is self:
            CallTracker._current_instance = None

    @classmethod
    def get_current(cls) -> CallTracker | None:
        """Gibt die aktuelle CallTracker-Instanz zurück."""
        return cls._current_instance


def get_current_tracker() -> CallTracker | None:
    """Hilfsfunktion für Tool-Module."""
    return CallTracker.get_current()
