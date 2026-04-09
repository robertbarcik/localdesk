"""Layer 3: LLM-as-judge — uses the same model to evaluate response quality."""

import json
import logging
import time

from app.llm_client import get_client, get_model
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
        client = get_client()
        model = get_model()
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
                temperature=0.0,
                max_tokens=512,
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

            content = resp.choices[0].message.content.strip()

            # Try to parse JSON from response
            # The model might wrap it in markdown code fences
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            verdict = json.loads(content)
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
