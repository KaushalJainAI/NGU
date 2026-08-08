"""Shared OpenRouter routing config.

OpenRouter serves one model id from many upstream providers and picks one per
request, so an unpinned call can land anywhere (observed: GMICloud for
deepseek/deepseek-v4-flash). Where the deployment cares which provider serves
the request — price, quantization, latency, or data residency — pin it here.

`deepinfra/fp4` is an *endpoint tag* (provider + quantization), NOT a model id;
it belongs in OPENROUTER_PROVIDER_ORDER, never in LLM_MODEL.
"""

import os


def openrouter_extra_body():
    """Body params pinning provider routing. Empty dict = OpenRouter's default.

    OPENROUTER_PROVIDER_ORDER   comma-separated provider names, highest priority
                                first (e.g. "DeepInfra"). Unset = no pin.
    OPENROUTER_ALLOW_FALLBACKS  "False" restricts to the listed providers only;
                                if they are all down the request FAILS rather
                                than routing elsewhere. Defaults to True so a
                                single provider outage degrades price/quant
                                instead of taking the assistant offline.
    """
    order = [p.strip() for p in os.getenv('OPENROUTER_PROVIDER_ORDER', '').split(',') if p.strip()]
    if not order:
        return {}
    allow_fallbacks = os.getenv('OPENROUTER_ALLOW_FALLBACKS', 'True').strip().lower() not in ('false', '0', 'no')
    return {'provider': {'order': order, 'allow_fallbacks': allow_fallbacks}}
