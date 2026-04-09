"""Guardrail pipeline — orchestrates all 3 layers."""

from dataclasses import dataclass, field

from app.guardrails.audit import log_interaction
from app.guardrails.llm_judge import judge_response
from app.guardrails.output_validator import validate_output
from app.guardrails.static_filters import run_input_filters

SAFE_BLOCK_MESSAGE = (
    "I'm sorry, but I'm unable to process that request. "
    "If you need assistance with an IT issue, please describe your problem "
    "and I'll be happy to help."
)

INJECTION_BLOCK_MESSAGE = (
    "I'm sorry, but your message was flagged by our safety system. "
    "I'm here to help with IT support requests. Please describe the IT issue "
    "you need assistance with."
)


@dataclass
class PipelineResult:
    """Result of the full guardrail pipeline."""

    allowed: bool = True
    sanitized_input: str = ""
    response: str = ""
    guardrail_triggers: list[str] = field(default_factory=list)
    judge_verdict: dict = field(default_factory=dict)


def pre_process(user_input: str) -> PipelineResult:
    """Layer 1: Run static input filters before LLM call."""
    result = PipelineResult()
    filter_result = run_input_filters(user_input)

    result.sanitized_input = filter_result.sanitized_input

    if filter_result.blocked:
        result.allowed = False
        if filter_result.injection_detected:
            result.response = INJECTION_BLOCK_MESSAGE
            result.guardrail_triggers.append("injection_detected")
        else:
            result.response = filter_result.block_reason
            result.guardrail_triggers.append("input_blocked")

        log_interaction(
            user_input=user_input,
            sanitized_input=filter_result.sanitized_input,
            retrieved_chunks=[],
            model_response=result.response,
            tool_calls=[],
            judge_verdict={},
            guardrail_triggers=result.guardrail_triggers,
        )
        return result

    if filter_result.pii_detected:
        result.guardrail_triggers.append(
            f"pii_redacted: {[p['type'] for p in filter_result.pii_detected]}"
        )

    return result


def post_process(
    user_input: str,
    sanitized_input: str,
    model_response: str,
    context_chunks: list[dict],
    tool_calls: list[dict],
    pre_triggers: list[str],
) -> PipelineResult:
    """Layers 2 & 3: Validate output and run LLM judge."""
    result = PipelineResult()
    result.sanitized_input = sanitized_input
    result.guardrail_triggers = list(pre_triggers)

    # Layer 2: Static output validation
    output_validation = validate_output(model_response, context_chunks)
    if output_validation.flags:
        result.guardrail_triggers.extend(output_validation.flags)

    # Layer 3: LLM judge
    # Include both RAG chunks and tool results as context for the judge
    context_parts = [c.get("text", "") for c in context_chunks]
    for tc in tool_calls:
        context_parts.append(f"[Tool: {tc.get('name', '')}] {tc.get('result', '')}")
    context_text = "\n\n".join(context_parts)
    verdict = judge_response(sanitized_input, model_response, context_text)
    result.judge_verdict = verdict

    if verdict.get("verdict") == "BLOCK":
        result.response = SAFE_BLOCK_MESSAGE
        result.allowed = False
        result.guardrail_triggers.append(f"judge_blocked: {verdict.get('reason', '')}")
    elif verdict.get("verdict") == "FLAG":
        result.response = model_response
        result.guardrail_triggers.append(f"judge_flagged: {verdict.get('reason', '')}")
    else:
        result.response = model_response

    # Audit log
    log_interaction(
        user_input=user_input,
        sanitized_input=sanitized_input,
        retrieved_chunks=context_chunks,
        model_response=result.response,
        tool_calls=tool_calls,
        judge_verdict=verdict,
        guardrail_triggers=result.guardrail_triggers,
    )

    return result
