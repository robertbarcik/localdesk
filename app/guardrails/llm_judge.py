"""Layer 3: LLM-as-judge — uses the same model to evaluate response quality."""

import json
import logging
import time

from app.llm_client import chat_kwargs, get_role_client, parse_json_loosely
from app.prompts.judge_system import JUDGE_SYSTEM_PROMPT
from app.tracing import tracer

logger = logging.getLogger(__name__)


def judge_response(user_query: str, agent_response: str, retrieved_context: str) -> dict:
    """Evaluate the agent's response using the LLM as a judge.

    Returns dict with keys: verdict (PASS/FLAG/BLOCK), reason, details.
    """
    evaluation_input = json.dumps(
        {
            "user_query": user_query,
            "retrieved_context": retrieved_context,
            "agent_response": agent_response,
        }
    )

    try:
        client, model = get_role_client("judge")
        with tracer.start_as_current_span(
            "gen_ai.chat",
            attributes={
                "gen_ai.system": "openai",
                "gen_ai.request.model": model,
                "gen_ai.request.temperature": 0.0,
                "gen_ai.request.max_tokens": 512,
                "gen_ai.operation.name": "chat",
                "mu.llm_call_type": "judge",
            },
        ) as span:
            t0 = time.monotonic()
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": evaluation_input},
                ],
                **chat_kwargs(model, max_tokens=900, temperature=0.0),
            )
            duration = time.monotonic() - t0
            span.set_attribute("mu.llm_duration_s", round(duration, 3))
            span.set_attribute("gen_ai.response.model", model)
            if resp.usage:
                span.set_attribute(
                    "gen_ai.usage.prompt_tokens", resp.usage.prompt_tokens or 0
                )
                span.set_attribute(
                    "gen_ai.usage.completion_tokens", resp.usage.completion_tokens or 0
                )

            if resp.usage:
                from app.ops.metrics import record_llm_usage
                record_llm_usage(
                    "judge", model,
                    resp.usage.prompt_tokens or 0,
                    resp.usage.completion_tokens or 0,
                    duration,
                )

            content = resp.choices[0].message.content.strip()
            verdict = parse_json_loosely(content)
            # Ensure required fields
            if "verdict" not in verdict:
                verdict["verdict"] = "PASS"
            if "reason" not in verdict:
                verdict["reason"] = ""
            span.set_attribute("mu.judge_verdict", verdict["verdict"])
            return verdict
    except Exception as e:
        logger.warning("LLM judge failed: %s — defaulting to PASS", e)
        return {"verdict": "PASS", "reason": f"Judge evaluation failed: {e}", "details": {}}
