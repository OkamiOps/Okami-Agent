"""Score→100: erro nativo Gemini/Bedrock → ClassifiedError (alavanca certa) + self-test de capacidade."""
from __future__ import annotations


class _BotoErr(Exception):
    """Imita botocore.exceptions.ClientError: status/code escondidos em .response."""
    def __init__(self, code, status, msg):
        super().__init__(f"An error occurred ({code}) when calling the Converse operation: {msg}")
        self.response = {"Error": {"Code": code, "Message": msg},
                         "ResponseMetadata": {"HTTPStatusCode": status}}


class _GeminiErr(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code        # google-genai APIError expõe .code (status HTTP)


def test_classify_reads_boto3_response_status():
    from okami.llm.errors import classify
    assert classify(_BotoErr("ThrottlingException", 429, "rate exceeded")).reason == "rate_limit"
    assert classify(_BotoErr("AccessDeniedException", 403, "no perms")).reason in ("auth_permanent", "auth")
    assert classify(_BotoErr("ServiceUnavailableException", 503, "busy")).reason == "overloaded"
    assert classify(_BotoErr("ValidationException", 400, "bad")).reason in ("bad_request", "not_found", "invalid_request")
    assert classify(_BotoErr("ResourceNotFoundException", 404, "no model")).reason == "not_found"


def test_classify_reads_gemini_code():
    from okami.llm.errors import classify
    assert classify(_GeminiErr(429, "Resource exhausted")).reason == "rate_limit"
    assert classify(_GeminiErr(401, "API key not valid")).reason == "auth"


def test_classify_boto3_routes_recovery_lever():
    from okami.llm.errors import classify
    rl = classify(_BotoErr("ThrottlingException", 429, "x"))
    assert rl.retryable and rl.fallback          # rate-limit → retry + failover (alavanca certa)


# ── self-test de capacidade do transporte nativo (sem rede/SDK) ──
def test_native_capability_self_check_gemini():
    from okami.llm.provider_check import check_native_transport
    rep = check_native_transport("gemini_native")
    assert rep["ok"] and rep["text"] and rep["tools"] and rep["image"] and rep["tool_call"]


def test_native_capability_self_check_bedrock():
    from okami.llm.provider_check import check_native_transport
    rep = check_native_transport("bedrock_native")
    assert rep["ok"] and rep["text"] and rep["tools"] and rep["image"] and rep["tool_call"]


def test_native_capability_self_check_unknown():
    from okami.llm.provider_check import check_native_transport
    assert check_native_transport("litellm")["ok"] is False   # não é transporte nativo
