"""
LiveKit Dispatch Rules & Trunks Diagnostic Tool

Dieses Skript überprüft Ihre LiveKit SIP-Konfiguration:
- Listet alle Dispatch Rules auf
- Listet alle SIP Trunks (Inbound/Outbound) auf
- Zeigt an, ob Konfiguration für eingehende Anrufe vorhanden ist
"""

import os
from dotenv import load_dotenv
from livekit import api

# .env.local laden
load_dotenv(".env.local")

# LiveKit Client initialisieren
livekit_url = os.getenv("LIVEKIT_URL")
api_key = os.getenv("LIVEKIT_API_KEY")
api_secret = os.getenv("LIVEKIT_API_SECRET")

print("=" * 70)
print("🔍 LiveKit SIP Konfiguration Diagnose")
print("=" * 70)
print()

# SIP Service Client erstellen
sip_client = api.SIPServiceClient(
    livekit_url.replace("wss://", "https://").replace("ws://", "http://"),
    api_key,
    api_secret,
)

print("📋 DISPATCH RULES")
print("-" * 70)

try:
    dispatch_rules = sip_client.list_dispatch_rule()
    
    if not dispatch_rules or len(dispatch_rules) == 0:
        print("❌ PROBLEM GEFUNDEN: Keine Dispatch Rules konfiguriert!")
        print()
        print("   → Eingehende Anrufe werden NICHT weitergeleitet")
        print("   → Sie müssen eine Dispatch Rule erstellen")
        print()
    else:
        print(f"✅ {len(dispatch_rules)} Dispatch Rule(s) gefunden:")
        print()
        for idx, rule in enumerate(dispatch_rules, 1):
            print(f"   {idx}. Name: {rule.name or 'Unnamed'}")
            print(f"      ID: {rule.dispatch_rule_id}")
            print(f"      Trunk IDs: {rule.trunk_ids or 'Alle Trunks'}")
            print(f"      Metadata: {rule.metadata or 'Keine'}")
            print()

except Exception as e:
    print(f"❌ Fehler beim Abrufen der Dispatch Rules: {e}")
    print()

print("📞 SIP TRUNKS (INBOUND)")
print("-" * 70)

try:
    inbound_trunks = sip_client.list_inbound_trunk()
    
    if not inbound_trunks or len(inbound_trunks) == 0:
        print("❌ PROBLEM GEFUNDEN: Keine Inbound Trunks konfiguriert!")
        print()
        print("   → Ihr LiveKit-Projekt kann keine SIP-Anrufe empfangen")
        print("   → Sie müssen einen Inbound Trunk für DIDWW erstellen")
        print()
    else:
        print(f"✅ {len(inbound_trunks)} Inbound Trunk(s) gefunden:")
        print()
        for idx, trunk in enumerate(inbound_trunks, 1):
            print(f"   {idx}. Name: {trunk.name or 'Unnamed'}")
            print(f"      ID: {trunk.sip_trunk_id}")
            print(f"      Numbers: {trunk.numbers or 'Alle Nummern'}")
            print(f"      Allowed Addresses: {trunk.allowed_addresses or 'Alle IPs'}")
            print()

except Exception as e:
    print(f"❌ Fehler beim Abrufen der Inbound Trunks: {e}")
    print()

print("📤 SIP TRUNKS (OUTBOUND)")
print("-" * 70)

try:
    outbound_trunks = sip_client.list_outbound_trunk()
    
    if not outbound_trunks or len(outbound_trunks) == 0:
        print("ℹ️  Keine Outbound Trunks konfiguriert (nicht erforderlich für eingehende Anrufe)")
        print()
    else:
        print(f"✅ {len(outbound_trunks)} Outbound Trunk(s) gefunden:")
        print()
        for idx, trunk in enumerate(outbound_trunks, 1):
            print(f"   {idx}. Name: {trunk.name or 'Unnamed'}")
            print(f"      ID: {trunk.sip_trunk_id}")
            print(f"      Address: {trunk.address}")
            print()

except Exception as e:
    print(f"❌ Fehler beim Abrufen der Outbound Trunks: {e}")
    print()

print("=" * 70)
print("🎯 ZUSAMMENFASSUNG")
print("=" * 70)
print()
print("Für eingehende SIP-Anrufe benötigen Sie:")
print("  1. ✅ Mindestens 1 Inbound Trunk (DIDWW)")
print("  2. ✅ Mindestens 1 Dispatch Rule (Route zu Room)")
print("  3. ✅ Agent läuft und ist registriert")
print()
print("Falls etwas fehlt, folgen Sie der Anleitung in:")
print("  → diagnostic_checklist.md")
print()
print("=" * 70)
