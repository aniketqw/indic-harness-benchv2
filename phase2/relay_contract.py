
"""Extend the tested provider wire contract for the 120B GPT-OSS variant."""

import json

import legacy_contract


# Phase-two models validated against a frozen legacy profile with identical settings.
LEGACY = {'gpt-oss:120b': 'gpt-oss:20b', 'glm-5.3-flash': 'nemotron-3-super'}
STREAMING = {'nemotron-3-super', 'glm-5.3-flash'}


def profile_for_legacy(profile):
    model = profile.get('model')
    if model not in LEGACY:
        return profile
    if profile.get('response_model_aliases') != [model]:
        raise ValueError('The phase-two response model must be pinned to the configured model')
    return {**profile, 'model': LEGACY[model], 'response_model_aliases': [LEGACY[model]]}


def validate_profile(profile):
    if profile.get('model') not in {*LEGACY, 'nemotron-3-super'}:
        raise ValueError('Unrecognized phase-two model')
    legacy_contract.validate_profile(profile_for_legacy(profile))
    return profile


def request_payload(request, profile):
    validate_profile(profile)
    model = profile['model']
    if request.get('model') != model:
        raise ValueError('Configured model only')
    compatible = profile_for_legacy(profile)
    payload = legacy_contract.request_payload({**request, 'model': compatible['model']}, compatible)
    if model in STREAMING:
        payload.update(stream=True, stream_options={'include_usage': True})
    return {**payload, 'model': model}


def completion(data, profile):
    validate_profile(profile)
    model = profile['model']
    if not isinstance(data, dict) or data.get('model') != model:
        raise ValueError('Unverified provider model identity')
    compatible = profile_for_legacy(profile)
    normalized, calls, errors = legacy_contract.completion({**data, 'model': compatible['model']}, compatible)
    return {**normalized, 'model': model}, calls, errors


stream_chunks = legacy_contract.stream_chunks
retry_delay = legacy_contract.retry_delay


def provider_error_category(body):
    """Log a fixed category without exposing provider text or request content."""
    try:
        error = json.loads(body).get('error', {})
        if isinstance(error, dict):
            error = ' '.join(str(error.get(k, '')) for k in ('code', 'type', 'message'))
        value = str(error).casefold()
    except (ValueError, AttributeError):
        return 'unclassified_provider_error'
    if any(word in value for word in ('tool_call', 'tool call', 'function call')):
        return 'provider_tool_call_error'
    if any(word in value for word in ('context length', 'context window', 'too many tokens')):
        return 'provider_context_error'
    if any(word in value for word in ('overload', 'capacity', 'unavailable', 'timeout', 'timed out')):
        return 'provider_availability_error'
    return 'unclassified_provider_error'
