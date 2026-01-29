
import inspect
from livekit.agents import AgentSession
from livekit.plugins.turn_detector.multilingual import MultilingualModel

with open("signatures.txt", "w") as f:
    f.write(f"AgentSession: {inspect.signature(AgentSession.__init__)}\n")
    f.write(f"MultilingualModel: {inspect.signature(MultilingualModel.__init__)}\n")
