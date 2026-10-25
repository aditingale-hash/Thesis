"""Fake model and fake pipeline for testing the agent loop without Ollama or a browser."""

import json

from agent.model_client import ModelError, ModelResponse
from pipelines.base import EXECUTED, FINISH_SPEC, ActionResult, InteractionPipeline, Observation


def reply(action: str, **args) -> str:
    return json.dumps({"thought": "test", "action": action, "args": args})


class FakeModel:
    """Returns the scripted responses in order; records every prompt it receives."""

    def __init__(self, responses, fail_at: int | None = None):
        self.responses = list(responses)
        self.prompts, self.images = [], []
        self.fail_at = fail_at

    def chat(self, prompt, image_b64=None, schema=None):
        if self.fail_at is not None and len(self.prompts) == self.fail_at:
            raise ModelError("connection refused")
        self.prompts.append(prompt)
        self.schemas = getattr(self, "schemas", []) + [schema]
        self.images.append(image_b64)
        text = self.responses.pop(0) if self.responses else reply("finish")
        return ModelResponse(text=text, input_tokens=100, output_tokens=10, duration_ms=5.0, wall_ms=6.0)


class FakePipeline(InteractionPipeline):
    """A text pipeline with actions click(ref) and type(ref, text); scripted statuses."""

    name = "fake"

    def __init__(self, statuses=None, observation_text="page 0", modality="text", crash_on_observe=False):
        self.statuses = list(statuses or [])
        self.executed = []
        self.n = 0
        self.observation_text = observation_text
        self.modality = modality
        self.crash_on_observe = crash_on_observe

    def attach(self, session): pass

    def action_space(self):
        return "click(ref: integer)\ntype(ref: integer, text: string)\nfinish()"

    def action_specs(self):
        return {"click": {"ref": ("integer", True)}, "type": {"ref": ("integer", True), "text": ("string", True)},
                **FINISH_SPEC}

    def observe(self):
        if self.crash_on_observe:
            raise RuntimeError("browser crashed")
        self.n += 1
        text = f"{self.observation_text} #{self.n}"
        if self.modality == "image":
            return Observation("image", "iVBORw0KGgo=", 8, "Screenshot attached.")
        return Observation("text", text, len(text), text)

    def execute(self, action):
        self.executed.append(action)
        status = self.statuses.pop(0) if self.statuses else EXECUTED
        return ActionResult(status, "" if status == EXECUTED else f"{status} message", 'page "X"')

    def truncate(self, observation, max_chars):
        return observation.prompt_text[:max_chars]
