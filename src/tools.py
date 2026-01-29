import logging
import os
from datetime import datetime
from time import perf_counter
from zoneinfo import ZoneInfo

import aiohttp
from livekit.agents import function_tool

from call_tracker import get_current_tracker

logger = logging.getLogger("friseur-agent")

# n8n Webhook URLs
N8N_CHECK_AVAILABILITY_WEBHOOK = os.getenv("N8N_CHECK_AVAILABILITY_WEBHOOK")


# Service-Katalog mit Dauern
SERVICE_CATALOG = [
    {
        "service": "Waschen + Schneiden + Gehen (Kurz)",
        "duration": 20,
        "category": "Damen",
    },
    {
        "service": "Waschen + Schneiden + Gehen (Nackenlang)",
        "duration": 30,
        "category": "Damen",
    },
    {
        "service": "Waschen + Schneiden + Gehen (Schulterlang)",
        "duration": 40,
        "category": "Damen",
    },
    {"service": "Waschen + Föhnen / Legen (Kurz)", "duration": 30, "category": "Damen"},
    {
        "service": "Waschen + Föhnen / Legen (Nackenlang)",
        "duration": 40,
        "category": "Damen",
    },
    {
        "service": "Waschen + Föhnen / Legen (Schulterlang)",
        "duration": 50,
        "category": "Damen",
    },
    {
        "service": "Waschen + Föhnen / Legen (Länger als Schultern)",
        "duration": 60,
        "category": "Damen",
    },
    {
        "service": "Waschen + Schneiden + Föhnen / Legen (Kurz)",
        "duration": 30,
        "category": "Damen",
    },
    {
        "service": "Waschen + Schneiden + Föhnen / Legen (Nackenlang)",
        "duration": 50,
        "category": "Damen",
    },
    {
        "service": "Waschen + Schneiden + Föhnen / Legen (Schulterlang)",
        "duration": 60,
        "category": "Damen",
    },
    {
        "service": "Waschen + Schneiden + Föhnen / Legen (Länger als Schultern)",
        "duration": 75,
        "category": "Damen",
    },
    {"service": "Herrenschnitt", "duration": 30, "category": "Herren"},
    {"service": "Färben Ansatz", "duration": 60, "category": "Färbung"},
    {"service": "Färben Neu", "duration": 90, "category": "Färbung"},
    {"service": "Pastellcolor / Glossing", "duration": 30, "category": "Färbung"},
    {"service": "Strähne Freihand", "duration": 60, "category": "Strähnen"},
    {"service": "Strähne Haube", "duration": 60, "category": "Strähnen"},
    {"service": "Strähne Folie", "duration": 90, "category": "Strähnen"},
    {"service": "Painting", "duration": 60, "category": "Strähnen"},
    {"service": "Babylights / Balayage", "duration": 180, "category": "Strähnen"},
    {"service": "Augenbrauen Färben", "duration": 15, "category": "Beauty"},
    {"service": "Wimpern Färben", "duration": 30, "category": "Beauty"},
    {"service": "Wimpernwelle + Wimpernfärben", "duration": 45, "category": "Beauty"},
    {"service": "Lashlifting + Färben", "duration": 60, "category": "Beauty"},
    {"service": "Augenbrauen Zupfen / Wachs", "duration": 15, "category": "Beauty"},
    {"service": "Oberlippe Enthaarung", "duration": 10, "category": "Beauty"},
]


@function_tool()
async def get_system_time() -> dict:
    """Ruft die aktuelle Systemzeit ab für Datumsberechnungen.

    Diese Funktion MUSS VOR check_availability() aufgerufen werden,
    um relative Datumsangaben (z.B. 'nächsten Samstag') korrekt zu berechnen.

    Returns:
        dict: Aktuelles Datum, Uhrzeit, Wochentag und Zeitzone.
            - current_date: Datum im Format YYYY-MM-DD
            - current_time: Uhrzeit im Format HH:MM
            - weekday: Wochentag auf Deutsch
            - weekday_number: Wochentag als Zahl (0=Montag, 6=Sonntag)
            - is_dst: Ob Sommerzeit aktiv ist
    """
    start_time = perf_counter()

    tz = ZoneInfo("Europe/Berlin")
    now = datetime.now(tz)

    weekdays = [
        "Montag",
        "Dienstag",
        "Mittwoch",
        "Donnerstag",
        "Freitag",
        "Samstag",
        "Sonntag",
    ]

    result = {
        "current_date": now.strftime("%Y-%m-%d"),
        "current_time": now.strftime("%H:%M"),
        "weekday": weekdays[now.weekday()],
        "weekday_number": now.weekday(),
        "is_dst": bool(now.dst()),
    }

    # Tool-Latenz tracken
    latency = perf_counter() - start_time
    tracker = get_current_tracker()
    if tracker:
        tracker.record_tool_call("get_system_time", latency, success=True)

    logger.info(f"System time retrieved: {result}")
    return result


@function_tool()
async def check_availability(
    date: str,
    time_slot: str,
    service: str,
    duration: int,
) -> dict:
    """Prüft die Terminverfügbarkeit beim Friseur-Salon.

    WICHTIG: Rufe IMMER zuerst get_system_time() auf, bevor du diese Funktion nutzt,
    um relative Datumsangaben korrekt zu berechnen.

    Args:
        date: Datum im Format YYYY-MM-DD (z.B. "2026-02-15")
        time_slot: Uhrzeit im Format HH:MM (z.B. "14:30")
        service: Name der Dienstleistung (z.B. "Herrenschnitt")
        duration: Dauer in Minuten (aus SERVICE_CATALOG)

    Returns:
        dict: Verfügbarkeit-Information
            - status: "available", "alternatives" oder "error"
            - message: Beschreibung des Ergebnisses
            - slots_primary: Liste der primären verfügbaren Slots
            - slots_secondary: Liste der sekundären Slots (falls Wunschtermin belegt)
            - Bei Fehler: type und missing_field
    """
    start_time_perf = perf_counter()
    tracker = get_current_tracker()

    if not N8N_CHECK_AVAILABILITY_WEBHOOK:
        logger.error("N8N_CHECK_AVAILABILITY_WEBHOOK not configured")
        latency = perf_counter() - start_time_perf
        if tracker:
            tracker.record_tool_call(
                "check_availability",
                latency,
                success=False,
                error_message="Webhook not configured",
            )
        return {
            "status": "error",
            "type": "configuration_error",
            "message": "Webhook URL ist nicht konfiguriert",
        }

    payload = {
        "date": date,
        "time": time_slot,
        "service": service,
        "duration": duration,
    }

    logger.info(f"Checking availability with payload: {payload}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                N8N_CHECK_AVAILABILITY_WEBHOOK,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                result = await response.json()
                latency = perf_counter() - start_time_perf
                if tracker:
                    tracker.record_tool_call(
                        "check_availability", latency, success=True
                    )
                logger.info(f"Availability check result: {result}")
                return result
    except aiohttp.ClientError as e:
        logger.error(f"Error checking availability: {e}")
        latency = perf_counter() - start_time_perf
        if tracker:
            tracker.record_tool_call(
                "check_availability", latency, success=False, error_message=str(e)
            )
        return {
            "status": "error",
            "type": "network_error",
            "message": f"Fehler beim Abrufen der Verfügbarkeit: {str(e)}",
        }
    except Exception as e:
        logger.error(f"Unexpected error checking availability: {e}")
        latency = perf_counter() - start_time_perf
        if tracker:
            tracker.record_tool_call(
                "check_availability", latency, success=False, error_message=str(e)
            )
        return {
            "status": "error",
            "type": "unknown_error",
            "message": f"Unerwarteter Fehler: {str(e)}",
        }
