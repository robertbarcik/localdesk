"""LocalDesk — main FastAPI application with chat orchestration."""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import SERVER_HOST, SERVER_PORT
from app.guardrails.pipeline import post_process, pre_process
from app.llm_client import get_client, get_model
from app.prompts.agent_system import AGENT_SYSTEM_PROMPT
from app.tools.assets import lookup_asset
from app.tools.definitions import TOOLS
from app.tools.incidents import create_incident, escalate_ticket
from app.tools.knowledge import search_kb
from app.tools.sla import check_sla

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


@app.post("/api/chat")
async def chat(request: Request) -> JSONResponse:
    body = await request.json()
    user_message = body.get("message", "").strip()
    session_id = body.get("session_id", "default")

    if not user_message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    # Layer 1: Pre-process (input filters)
    pre_result = pre_process(user_message)
    if not pre_result.allowed:
        return JSONResponse(
            {
                "response": pre_result.response,
                "tool_calls": [],
                "guardrail_triggers": pre_result.guardrail_triggers,
            }
        )

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

    for _ in range(max_iterations):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            temperature=0.3,
            max_tokens=1024,
        )
        choice = resp.choices[0]

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

                handler = TOOL_HANDLERS.get(fn_name)
                if handler:
                    tool_result = handler(fn_args)
                    logger.info("Tool call: %s(%s)", fn_name, fn_args)
                else:
                    tool_result = json.dumps({"error": f"Unknown tool: {fn_name}"})

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
    messages.append({"role": "assistant", "content": assistant_content})

    # Keep conversation manageable (last 20 messages + system)
    if len(messages) > 40:
        _conversations[session_id] = [messages[0]] + messages[-20:]

    # Layers 2 & 3: Post-process (output validation + LLM judge)
    post_result = post_process(
        user_input=user_message,
        sanitized_input=pre_result.sanitized_input,
        model_response=assistant_content,
        context_chunks=context_chunks,
        tool_calls=all_tool_calls,
        pre_triggers=pre_result.guardrail_triggers,
    )

    return JSONResponse(
        {
            "response": post_result.response,
            "tool_calls": [
                {"name": tc["name"], "arguments": tc["arguments"]}
                for tc in all_tool_calls
            ],
            "guardrail_triggers": post_result.guardrail_triggers,
            "judge_verdict": post_result.judge_verdict.get("verdict", "PASS"),
        }
    )


@app.post("/api/reset")
async def reset_session(request: Request) -> JSONResponse:
    body = await request.json()
    session_id = body.get("session_id", "default")
    _conversations.pop(session_id, None)
    return JSONResponse({"status": "ok"})


def main():
    import uvicorn

    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT, log_level="info")


if __name__ == "__main__":
    main()
