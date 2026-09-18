"""The pipecat pipeline builds with dummy keys. Nothing runs, nothing connects.

This catches import paths and constructor signatures that drift between
pipecat releases, without a key and without a network.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from vortex import tools as registry
from vortex.contract import MADRID
from vortex.conversation.prompt import initial_messages
from vortex.conversation.turns import default_turn_settings


def test_pipecat_modules_import() -> None:
    pytest.importorskip("pipecat")
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from pipecat.audio.vad.silero import SileroVADAnalyzer  # noqa: F401
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (  # noqa: F401
        LLMContextAggregatorPair,
    )
    from pipecat.serializers.twilio import TwilioFrameSerializer
    from pipecat.services.deepgram.stt import DeepgramSTTService  # noqa: F401
    from pipecat.services.openai.llm import OpenAILLMService  # noqa: F401
    from pipecat.services.openai.tts import OpenAITTSService  # noqa: F401
    from pipecat.transports.websocket.fastapi import (  # noqa: F401
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )

    serializer = TwilioFrameSerializer(
        stream_sid="MZ-x",
        call_sid="CA-x",
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )
    assert serializer is not None

    schemas = []
    for fn in registry.function_schemas(default_turn_settings().exposed_tools):
        props = dict(fn["parameters"]["properties"])
        if fn["parameters"].get("$defs"):
            props["$defs"] = fn["parameters"]["$defs"]
        schemas.append(
            FunctionSchema(
                name=fn["name"],
                description=fn["description"],
                properties=props,
                required=fn["parameters"]["required"],
            )
        )
    context = LLMContext(
        initial_messages(datetime.now(MADRID)), tools=ToolsSchema(standard_tools=schemas)
    )
    assert context is not None
