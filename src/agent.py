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
    room_io,
)
from livekit.plugins import deepgram, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

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
        # OpenRouter LLM - GPT-4.1 mini
        llm=openai.LLM.with_openrouter(
            model="openai/gpt-4.1-mini",
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
    )

    # Session starten
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

    # Mit Room verbinden
    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
