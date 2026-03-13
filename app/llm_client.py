from openai import OpenAI

from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

_client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


def get_client() -> OpenAI:
    return _client


def get_model() -> str:
    return LLM_MODEL
