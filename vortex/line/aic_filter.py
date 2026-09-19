"""Optional ai-coustics ``AICFilter`` for the Twilio input path.

Wired into ``FastAPIWebsocketParams.audio_in_filter`` only when
``VORTEX_AIC_FILTER`` is on and ``AIC_SDK_LICENSE`` is set. Default is off:
generic denoisers often raise WER on modern ASR (Dec 2025 paper, 40/40
configs), and Quail still needs a measured entity-CER drop on the T54 5 dB
bench before the live path should flip on. See
``docs/research/01-noise-suppression.md``.

Real runs need ``pipecat-ai[aic]`` (pulled in via the project's pipecat
extras). Tests inject a fake filter class so nothing calls the vendor.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Native 8 kHz Quail Multi Speaker L — matches Twilio Media Streams sample rate.
AIC_MODEL_ID = "quail-ms-l-8khz"


def build_audio_in_filter(settings: Any, *, filter_cls: type | None = None) -> Any | None:
    """Return an ``AICFilter`` for the transport, or ``None`` to leave the path raw.

    ``filter_cls`` is the real ``AICFilter`` unless a test injects a stand-in.
    Construction does not download the model or open a network socket; that
    happens when the transport starts the filter on the first audio frame.
    """
    if not settings.aic_filter_enabled:
        return None
    license_key = settings.aic_sdk_license
    if not license_key:
        log.warning("VORTEX_AIC_FILTER is on but AIC_SDK_LICENSE is empty; filter stays off")
        return None
    cls = filter_cls
    if cls is None:
        try:
            from pipecat.audio.filters.aic_filter import AICFilter
        except ImportError:
            log.warning("pipecat-ai[aic] / aic-sdk is not installed; filter stays off")
            return None
        cls = AICFilter
    model_id = settings.aic_model_id or AIC_MODEL_ID
    return cls(license_key=license_key, model_id=model_id)
