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

logger = logging.getLogger("friseur-agent")

load_dotenv(".env.local")

# Deepgram EU Endpoint - DSGVO-konform
DEEPGRAM_EU_BASE_URL = "https://api.eu.deepgram.com/v1/speak"
DEEPGRAM_EU_ENDPOINT_URL = "https://api.eu.deepgram.com/v1/listen"


class FriseurAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""Du bist die freundliche Telefonassistentin eines Friseur-Salons in Deutschland.

WICHTIG:
- Sprich immer auf Deutsch
- Sei höflich, freundlich und professionell
- Halte deine Antworten kurz und prägnant (maximal 2-3 Sätze)
- Verwende keine Emojis, Sonderzeichen oder Formatierungen
- Sprich natürlich und menschlich

BEGRÜSSUNG:
Wenn ein Anruf beginnt, begrüße den Anrufer herzlich:
"Guten Tag, Sie sind verbunden mit dem Friseur-Salon. Wie kann ich Ihnen helfen?"

DEINE AUFGABEN:
- Anrufer freundlich begrüßen
- Allgemeine Fragen zum Salon beantworten
- Bei Fragen zu Terminen: "Termine können Sie derzeit leider nur telefonisch mit unseren Mitarbeitern vereinbaren."
- Bei komplexen Anfragen: An einen Mitarbeiter verweisen

WICHTIGE HINWEISE:
- Terminbuchungsfunktion ist derzeit noch nicht verfügbar
- Bei Unsicherheit: Höflich um Wiederholung bitten
- Immer professionell und hilfsbereit bleiben
""",
        )


server = AgentServer()


def prewarm(proc: JobProcess):
    """Modelle vorladen für schnellere Antwortzeiten"""
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
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
            endpoint_url=DEEPGRAM_EU_ENDPOINT_URL,
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
