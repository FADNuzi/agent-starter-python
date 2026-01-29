import logging

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    cli,
    metrics,
    room_io,
)
from livekit.plugins import deepgram, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from call_tracker import CallTracker
from tools import check_availability, get_system_time

logger = logging.getLogger("friseur-agent")

load_dotenv(".env.local")

# Deepgram EU Endpoint - DSGVO-konform
DEEPGRAM_EU_BASE_URL = "https://api.eu.deepgram.com/v1/speak"
DEEPGRAM_EU_ENDPOINT_URL = "https://api.eu.deepgram.com/v1/listen"


class FriseurAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""Du bist die freundliche Telefonassistentin des Friseur-Salons Haarparadies.

SPRACHE & STIL:
- Sprich immer auf Deutsch, höflich, freundlich und professionell
- Halte deine Antworten kurz und prägnant (maximal 2-3 Sätze)
- Verwende keine Emojis, Sonderzeichen oder Formatierungen
- Sprich natürlich und menschlich

BEGRÜSSUNG:
Wenn ein Anruf beginnt, begrüße den Anrufer herzlich:
"Guten Tag, Sie sind verbunden mit dem Haarparadies. Wie kann ich Ihnen helfen?"

TERMINBUCHUNG - ABLAUF:

1. SERVICE ERFRAGEN
   Frage nach der gewünschten Dienstleistung und Haarlänge (falls relevant).
   Beispiele:
   - Herrenschnitt (30 Min)
   - Damenschnitt: kurz (20 Min), nackenlang (30 Min), schulterlang (40 Min)
   - Färben Ansatz (60 Min), Färben Neu (90 Min)
   - Strähnen Folie (90 Min), Babylights/Balayage (180 Min)
   - Beauty: Augenbrauen Färben (15 Min), Wimpern Färben (30 Min)

2. SYSTEMZEIT ABRUFEN
   Rufe IMMER get_system_time() auf, BEVOR du check_availability() nutzt.
   Dies ist ZWINGEND erforderlich für korrekte Datumsberechnungen.

3. DATUM & UHRZEIT ERFRAGEN
   Frage nach dem Wunschtermin. Berechne aus relativen Angaben das konkrete Datum:
   - "nächsten Samstag" → berechne aus aktuellem Wochentag + Datum
   - "morgen" → aktuelles Datum + 1 Tag
   - "übermorgen" → aktuelles Datum + 2 Tage

4. VERFÜGBARKEIT PRÜFEN
   Rufe check_availability() mit allen 4 Parametern auf:
   - date: YYYY-MM-DD Format
   - time: HH:MM Format
   - service: Exakter Name der Dienstleistung
   - duration: Dauer in Minuten (aus obiger Liste)

5. ERGEBNIS KOMMUNIZIEREN
   - status="available": "Der Termin am [Tag] um [Zeit] Uhr ist frei! Soll ich den Termin für Sie reservieren?"
   - status="alternatives": "Der Wunschtermin ist leider belegt. Ich habe folgende Alternativen: [Slots auflisten]"
   - status="error": Fehlende Information höflich nachfragen

WICHTIGE HINWEISE:
- Terminbuchung ist derzeit in Entwicklung
- Bei komplexen Anfragen: An einen Mitarbeiter verweisen
- Bei Unsicherheit: Höflich um Wiederholung bitten
- Immer professionell und hilfsbereit bleiben
""",
            tools=[get_system_time, check_availability],
        )

    async def on_enter(self):
        """Wird aufgerufen, wenn der Agent dem Room beitritt.
        Generiert proaktiv die Begrüßung."""
        self.session.generate_reply()


server = AgentServer()


def prewarm(proc: JobProcess):
    """Modelle vorladen für schnellere Antwortzeiten"""
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="haarparadies-agent")
async def friseur_agent(ctx: JobContext):
    # Logging-Kontext
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # Voice AI Pipeline mit Deepgram STT/TTS (EU) + OpenRouter LLM
    session = AgentSession(
        # Deepgram STT - Nova 3 (Deutsch) - EU Endpoint
        stt=deepgram.STT(
            model="nova-3",
            language="de",
        ),
        # OpenRouter LLM - GPT-4.1
        llm=openai.LLM.with_openrouter(
            model="openai/gpt-4.1",
        ),
        # Deepgram TTS - Aura 2 Viktoria (Deutsch) - EU Endpoint
        tts=deepgram.TTS(
            model="aura-2-viktoria-de",
            base_url=DEEPGRAM_EU_BASE_URL,
        ),
        # VAD + Turn Detection
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        # Preemptive generation für schnellere Antworten
        preemptive_generation=True,
        # Endpointing Delay Tuning
        min_endpointing_delay=0.3,
    )

    # ZUERST mit Room verbinden (damit room.sid verfügbar ist)
    await ctx.connect()

    # CallTracker initialisieren NACH connect (room.sid ist jetzt ein String)
    call_tracker = CallTracker(
        call_id=ctx.job.id,  # Job-ID als eindeutige Call-ID verwenden
        room_name=ctx.room.name,
    )

    # =========================================================================
    # METRICS EVENT HANDLERS
    # =========================================================================

    def on_metrics_collected(event):
        """Handler für alle Pipeline-Metriken (STT, LLM, TTS, VAD, EOU).

        Der Event ist ein MetricsCollectedEvent mit einem 'metrics' Attribut.
        """
        # Extrahiere die AgentMetrics aus dem Event
        agent_metrics = event.metrics if hasattr(event, "metrics") else event
        # An CallTracker weiterleiten (mit Verbose-Ausgabe)
        call_tracker.record_metrics(agent_metrics)
        # Auch an LiveKit Cloud Insights senden
        metrics.log_metrics(agent_metrics)

    # Event-Handler registrieren
    session.on("metrics_collected", on_metrics_collected)

    # =========================================================================
    # E2E LATENZ TRACKING & TURN MANAGEMENT
    # =========================================================================

    # =========================================================================
    # E2E LATENZ TRACKING & TURN MANAGEMENT
    # =========================================================================

    def on_user_speech_started(*args):
        """Wird aufgerufen wenn der User anfängt zu sprechen."""
        logger.info("⚡ EVENT: user_speech_started")
        # Neuen Turn genau dann starten, wenn der User anfängt
        call_tracker.start_new_turn()

    def on_user_turn_completed(*args):
        """Wird aufgerufen wenn der User aufhört zu sprechen."""
        logger.info("⚡ EVENT: user_turn_completed")
        call_tracker.mark_user_speech_end()

    def on_agent_speech_started(*args):
        """Wird aufgerufen wenn der Agent anfängt zu sprechen."""
        logger.info("⚡ EVENT: agent_speech_started")
        call_tracker.mark_first_agent_audio()

    def on_agent_speech_stopped(*args):
        """Wird aufgerufen wenn der Agent aufhört zu sprechen."""
        logger.info("⚡ EVENT: agent_speech_stopped")

    session.on("user_speech_started", on_user_speech_started)
    session.on("user_turn_completed", on_user_turn_completed)
    session.on("agent_speech_started", on_agent_speech_started)
    session.on("agent_speech_stopped", on_agent_speech_stopped)

    # =========================================================================
    # SESSION LIFECYCLE
    # =========================================================================

    async def on_session_end():
        """Wird aufgerufen wenn die Session endet."""
        logger.info("Session ending, finalizing call tracker...")
        await call_tracker.finalize()

    # DANN Session starten
    await session.start(
        agent=FriseurAssistant(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                # Noise Cancellation für Telefonie
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )

    # Warten bis Session beendet wird (Participant disconnect)
    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(participant):
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            logger.info(f"SIP participant {participant.identity} disconnected")
            # Session-Ende Handler aufrufen
            import asyncio

            asyncio.create_task(on_session_end())


if __name__ == "__main__":
    # Logging aktivieren, um Startup-Errors zu sehen
    logging.basicConfig(level=logging.INFO)
    cli.run_app(server)
