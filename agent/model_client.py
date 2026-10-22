"""Ollama client.

One call = one model invocation: ``/api/chat`` without streaming, temperature 0,
fixed seed, and the common action JSON schema as structured output (``format``).
Token counts come from Ollama's ``prompt_eval_count`` / ``eval_count``.
"""

import time
from dataclasses import dataclass

import httpx

# The ONE action format of all pipelines: {"thought": str, "action": str, "args": object}
ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "action": {"type": "string"},
        "args": {"type": "object"},
    },
    "required": ["thought", "action", "args"],
}


class ModelError(Exception):
    """The model runtime failed (connection, HTTP error, timeout). Leads to S5."""


@dataclass
class ModelResponse:
    text: str
    input_tokens: int
    output_tokens: int
    duration_ms: float          # Ollama's total_duration (model-side time)
    wall_ms: float              # wall-clock time of the HTTP call


class OllamaClient:
    """Calls a local Ollama server with the settings of ``config/model.yaml``."""

    def __init__(self, config: dict, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.http = httpx.Client(base_url=config["ollama_url"], timeout=config.get("request_timeout_s", 300),
                                 transport=transport)

    def chat(self, prompt: str, image_b64: str | None = None) -> ModelResponse:
        """Send one user message (optionally with one base64 PNG) and return the reply."""
        message = {"role": "user", "content": prompt}
        if image_b64:
            message["images"] = [image_b64]
        payload = {
            "model": self.config["model"],
            "messages": [message],
            "stream": False,
            "format": ACTION_SCHEMA,
            "options": {
                "temperature": self.config["temperature"],
                "seed": self.config["seed"],
                "num_ctx": self.config["num_ctx"],
                "num_predict": self.config["max_output_tokens"],
            },
        }
        start = time.perf_counter()
        try:
            r = self.http.post("/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ModelError(f"Ollama request failed: {e}") from e
        wall_ms = (time.perf_counter() - start) * 1000
        return ModelResponse(
            text=data.get("message", {}).get("content", ""),
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            duration_ms=data.get("total_duration", 0) / 1e6 or wall_ms,
            wall_ms=wall_ms,
        )

    def version(self) -> str:
        """Ollama server version."""
        return self.http.get("/api/version").json().get("version", "unknown")

    def model_info(self) -> dict:
        """Model digest (from /api/tags) and details (from /api/show)."""
        info = {"name": self.config["model"], "digest": None, "details": None}
        for m in self.http.get("/api/tags").json().get("models", []):
            if m.get("name") == self.config["model"] or m.get("model") == self.config["model"]:
                info["digest"] = m.get("digest")
        show = self.http.post("/api/show", json={"model": self.config["model"]}).json()
        info["details"] = show.get("details")
        return info

    def close(self) -> None:
        self.http.close()
