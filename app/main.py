"""LocalDesk — main FastAPI application with chat orchestration."""

import asyncio
import json
import logging
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from opentelemetry import trace
from starlette.responses import StreamingResponse

from app.config import DATABASE_PATH, MODE, SERVER_HOST, SERVER_PORT
from app.guardrails.pipeline import post_process, pre_process
from app.llm_client import get_client, get_model
from app.prompts.agent_system import AGENT_SYSTEM_PROMPT
from app.tools.assets import lookup_asset
from app.tools.definitions import TOOLS
from app.tools.incidents import create_incident, escalate_ticket
from app.tools.knowledge import search_kb
from app.tools.sla import check_sla
from app.tracing import tracer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Tool dispatch map
TOOL_HANDLERS = {
    "check_sla": lambda args: check_sla(**args),
    "create_incident": lambda args: create_incident(**args),
    "lookup_asset": lambda args: lookup_asset(**args),
    "escalate_ticket": lambda args: escalate_ticket(**args),
    "search_kb": lambda args: search_kb(**args),
}

# In-memory conversation store (session_id -> messages)
_conversations: dict[str, list[dict]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("LocalDesk starting up")
    yield
    logger.info("LocalDesk shutting down")


app = FastAPI(title="LocalDesk", lifespan=lifespan)

# Serve static files (frontend)
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = Path(__file__).parent.parent / "static" / "index.html"
    return HTMLResponse(index_path.read_text())


def _run_chat_pipeline(user_message: str, session_id: str) -> dict:
    """Core pipeline: pre-process -> LLM+tools -> post-process. Returns result dict."""
    with tracer.start_as_current_span(
        "chat_request",
        attributes={
            "mu.session_id": session_id,
            "mu.mode": MODE,
            "mu.user_message_length": len(user_message),
        },
    ) as root_span:

        # Layer 1: Pre-process (input filters)
        with tracer.start_as_current_span(
            "guardrail.pre_process",
            attributes={"guardrail.layer": "input_filter"},
        ) as pre_span:
            pre_result = pre_process(user_message)
            pre_span.set_attribute("guardrail.allowed", pre_result.allowed)
            if pre_result.guardrail_triggers:
                pre_span.set_attribute(
                    "guardrail.triggers", json.dumps(pre_result.guardrail_triggers)
                )

        if not pre_result.allowed:
            root_span.set_attribute("mu.blocked_by", "input_filter")
            root_span.set_attribute("mu.guardrail_triggers",
                                    json.dumps(pre_result.guardrail_triggers))
            return {
                "response": pre_result.response,
                "tool_calls": [],
                "guardrail_triggers": pre_result.guardrail_triggers,
                "judge_verdict": "PASS",
            }

        # Build conversation history
        if session_id not in _conversations:
            _conversations[session_id] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
        messages = _conversations[session_id]
        messages.append({"role": "user", "content": pre_result.sanitized_input})

        # LLM call with tool use loop
        client = get_client()
        model = get_model()
        all_tool_calls = []
        context_chunks = []
        max_iterations = 5
        llm_call_count = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0

        for iteration in range(max_iterations):
            with tracer.start_as_current_span(
                "gen_ai.chat",
                attributes={
                    "gen_ai.system": "openai",
                    "gen_ai.request.model": model,
                    "gen_ai.request.temperature": 0.3,
                    "gen_ai.request.max_tokens": 1024,
                    "gen_ai.operation.name": "chat",
                    "mu.llm_call_iteration": iteration,
                    "mu.tools_available": len(TOOLS),
                },
            ) as llm_span:
                t0 = time.monotonic()
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=TOOLS,
                    temperature=0.3,
                    max_tokens=1024,
                )
                duration = time.monotonic() - t0
                llm_call_count += 1
                choice = resp.choices[0]

                # Token usage
                if resp.usage:
                    total_prompt_tokens += resp.usage.prompt_tokens or 0
                    total_completion_tokens += resp.usage.completion_tokens or 0
                    llm_span.set_attribute(
                        "gen_ai.usage.prompt_tokens", resp.usage.prompt_tokens or 0
                    )
                    llm_span.set_attribute(
                        "gen_ai.usage.completion_tokens", resp.usage.completion_tokens or 0
                    )

                llm_span.set_attribute("gen_ai.response.model", model)
                llm_span.set_attribute(
                    "gen_ai.response.finish_reasons",
                    json.dumps([choice.finish_reason or "stop"]),
                )
                llm_span.set_attribute("mu.llm_duration_s", round(duration, 3))

            if choice.finish_reason == "tool_calls" or (
                choice.message.tool_calls and len(choice.message.tool_calls) > 0
            ):
                # Process tool calls
                messages.append(choice.message.model_dump())
                for tc in choice.message.tool_calls:
                    fn_name = tc.function.name
                    try:
                        fn_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        fn_args = {}

                    with tracer.start_as_current_span(
                        f"tool.{fn_name}",
                        attributes={
                            "mu.tool.name": fn_name,
                            "mu.tool.arguments": json.dumps(fn_args),
                        },
                    ) as tool_span:
                        handler = TOOL_HANDLERS.get(fn_name)
                        if handler:
                            tool_result = handler(fn_args)
                            logger.info("Tool call: %s(%s)", fn_name, fn_args)
                        else:
                            tool_result = json.dumps({"error": f"Unknown tool: {fn_name}"})
                            tool_span.set_attribute("mu.tool.error", True)

                        tool_span.set_attribute(
                            "mu.tool.result_length", len(tool_result)
                        )

                    all_tool_calls.append(
                        {"name": fn_name, "arguments": fn_args, "result": tool_result}
                    )

                    # If it was a KB search, track the chunks for guardrails
                    if fn_name == "search_kb":
                        try:
                            kb_result = json.loads(tool_result)
                            for r in kb_result.get("results", []):
                                context_chunks.append(
                                    {"text": r.get("content", ""), "source": r.get("source", "")}
                                )
                        except json.JSONDecodeError:
                            pass

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": tool_result,
                        }
                    )
            else:
                # Final response
                break

        assistant_content = choice.message.content or ""

        # If the model ended with tool calls and no text response, force a final response
        if not assistant_content and all_tool_calls:
            with tracer.start_as_current_span(
                "gen_ai.chat",
                attributes={
                    "gen_ai.system": "openai",
                    "gen_ai.request.model": model,
                    "gen_ai.request.temperature": 0.3,
                    "gen_ai.request.max_tokens": 1024,
                    "gen_ai.operation.name": "chat",
                    "mu.llm_call_type": "forced_final",
                },
            ) as final_span:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=1024,
                )
                assistant_content = resp.choices[0].message.content or ""
                llm_call_count += 1
                if resp.usage:
                    total_prompt_tokens += resp.usage.prompt_tokens or 0
                    total_completion_tokens += resp.usage.completion_tokens or 0
                    final_span.set_attribute(
                        "gen_ai.usage.prompt_tokens", resp.usage.prompt_tokens or 0
                    )
                    final_span.set_attribute(
                        "gen_ai.usage.completion_tokens", resp.usage.completion_tokens or 0
                    )
                final_span.set_attribute("gen_ai.response.model", model)

        messages.append({"role": "assistant", "content": assistant_content})

        # Keep conversation manageable (last 20 messages + system)
        if len(messages) > 40:
            _conversations[session_id] = [messages[0]] + messages[-20:]

        # Layers 2 & 3: Post-process (output validation + LLM judge)
        with tracer.start_as_current_span(
            "guardrail.post_process",
            attributes={"guardrail.layer": "output_validation_and_judge"},
        ) as post_span:
            post_result = post_process(
                user_input=user_message,
                sanitized_input=pre_result.sanitized_input,
                model_response=assistant_content,
                context_chunks=context_chunks,
                tool_calls=all_tool_calls,
                pre_triggers=pre_result.guardrail_triggers,
            )
            post_span.set_attribute(
                "guardrail.judge_verdict",
                post_result.judge_verdict.get("verdict", "PASS"),
            )
            if post_result.guardrail_triggers:
                post_span.set_attribute(
                    "guardrail.triggers", json.dumps(post_result.guardrail_triggers)
                )

        # Set summary attributes on root span
        root_span.set_attribute("gen_ai.request.model", model)
        root_span.set_attribute("mu.llm_call_count", llm_call_count)
        root_span.set_attribute("mu.tool_call_count", len(all_tool_calls))
        root_span.set_attribute("mu.total_prompt_tokens", total_prompt_tokens)
        root_span.set_attribute("mu.total_completion_tokens", total_completion_tokens)
        root_span.set_attribute("mu.total_tokens", total_prompt_tokens + total_completion_tokens)
        root_span.set_attribute(
            "mu.judge_verdict", post_result.judge_verdict.get("verdict", "PASS")
        )
        root_span.set_attribute("mu.response_length", len(post_result.response))
        if all_tool_calls:
            root_span.set_attribute(
                "mu.tools_used", json.dumps([tc["name"] for tc in all_tool_calls])
            )

        return {
            "response": post_result.response,
            "tool_calls": [
                {"name": tc["name"], "arguments": tc["arguments"]}
                for tc in all_tool_calls
            ],
            "guardrail_triggers": post_result.guardrail_triggers,
            "judge_verdict": post_result.judge_verdict.get("verdict", "PASS"),
        }


@app.post("/api/chat")
async def chat(request: Request) -> JSONResponse:
    body = await request.json()
    user_message = body.get("message", "").strip()
    session_id = body.get("session_id", "default")

    if not user_message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    result = _run_chat_pipeline(user_message, session_id)
    return JSONResponse(result)


@app.post("/api/chat-stream")
async def chat_stream(request: Request):
    """SSE streaming version — runs full pipeline then streams response word-by-word."""
    body = await request.json()
    user_message = body.get("message", "").strip()
    session_id = body.get("session_id", "default")

    if not user_message:
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': 'Empty message'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    async def event_stream():
        result = await asyncio.to_thread(_run_chat_pipeline, user_message, session_id)

        # Send metadata first
        meta = {
            "type": "meta",
            "tool_calls": result["tool_calls"],
            "guardrail_triggers": result["guardrail_triggers"],
            "judge_verdict": result["judge_verdict"],
        }
        yield f"data: {json.dumps(meta)}\n\n"

        # Stream response text word-by-word
        words = result["response"].split(" ")
        for i, word in enumerate(words):
            chunk = word if i == 0 else " " + word
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
            await asyncio.sleep(0.03)

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/reset")
async def reset_session(request: Request) -> JSONResponse:
    body = await request.json()
    session_id = body.get("session_id", "default")
    _conversations.pop(session_id, None)
    return JSONResponse({"status": "ok"})


@app.get("/api/status")
async def status() -> JSONResponse:
    from app.config import LLM_BASE_URL, LLM_MODEL, MODE

    return JSONResponse({"mode": MODE, "model": LLM_MODEL, "base_url": LLM_BASE_URL})


@app.get("/api/dashboard")
async def dashboard() -> JSONResponse:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        by_status = {}
        for row in conn.execute("SELECT status, COUNT(*) AS cnt FROM incidents GROUP BY status"):
            by_status[row["status"]] = row["cnt"]

        by_priority = {}
        for row in conn.execute("SELECT priority, COUNT(*) AS cnt FROM incidents GROUP BY priority"):
            by_priority[row["priority"]] = row["cnt"]

        total = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]

        recent = [
            dict(row)
            for row in conn.execute(
                "SELECT ticket_id, summary, priority, status, created_at "
                "FROM incidents ORDER BY created_at DESC LIMIT 5"
            )
        ]
    finally:
        conn.close()

    return JSONResponse({
        "by_status": by_status,
        "by_priority": by_priority,
        "total": total,
        "recent": recent,
    })


def main():
    import uvicorn

    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT, log_level="info")


if __name__ == "__main__":
    main()
