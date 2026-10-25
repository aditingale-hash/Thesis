"""Agent control loop with stopping conditions S1-S5.

Per step: observe -> build prompt -> invoke model -> record invocation -> parse ->
if finish: stop -> else execute -> record action -> add to history.
Exactly one action per model invocation.

S1 finish issued; S2 max model invocations reached; S3 max consecutive invalid actions;
S4 max task execution time; S5 infrastructure failure (browser, Ollama, shop).
``finish`` never means success: success is decided by the verifier afterwards.
"""

import time
from dataclasses import dataclass

from agent.action_parser import parse_action
from agent.context import History
from agent.model_client import ModelError
from agent.prompt import build_prompt
from pipelines.base import ERROR, EXECUTED, INVALID, REJECTED

S1, S2, S3, S4, S5 = "S1_finish", "S2_max_invocations", "S3_consecutive_invalid", "S4_timeout", "S5_infrastructure"


@dataclass
class LoopResult:
    termination_reason: str
    execution_time_ms: float
    detail: str = ""             # e.g. the infrastructure error for S5


class NullRecorder:
    """Recorder that records nothing (for tests)."""

    def invocation(self, **kwargs): pass
    def action(self, **kwargs): pass


def run_agent(pipeline, model, instruction: str, limits: dict, model_config: dict,
              recorder=None, clock=time.perf_counter) -> LoopResult:
    """Run the agent on one task until a stopping condition holds."""
    recorder = recorder or NullRecorder()
    history = History()
    start = clock()
    invocations = 0
    consecutive_invalid = 0

    def result(reason: str, detail: str = "") -> LoopResult:
        return LoopResult(reason, (clock() - start) * 1000, detail)

    step = 0
    while True:
        step += 1
        if invocations >= limits["max_invocations"]:
            return result(S2)
        if clock() - start >= limits["max_seconds"]:
            return result(S4)

        try:
            observation = pipeline.observe()
        except Exception as e:  # browser crashed, shop unreachable
            return result(S5, f"observe failed: {e}")
        prompt, truncated = build_prompt(pipeline, observation, instruction, history.lines, model_config)
        image = observation.content if observation.modality == "image" else None
        try:
            response = model.chat(prompt, image, pipeline.response_schema())
        except ModelError as e:
            return result(S5, str(e))
        invocations += 1
        recorder.invocation(step=step, input_tokens=response.input_tokens, output_tokens=response.output_tokens,
                            duration_ms=response.duration_ms, raw_response=response.text,
                            observation_size=observation.size, truncated=truncated,
                            perception_ms=getattr(observation, "perception_ms", None))

        parsed = parse_action(response.text, pipeline.action_specs())
        if parsed.action is None:
            recorder.action(step=step, name=None, args=None, status=INVALID, message=parsed.error,
                            duration_ms=0.0, parse_error=parsed.kind)
            history.add_invalid_response(step, parsed.error)
            consecutive_invalid += 1
            if consecutive_invalid >= limits["max_consecutive_invalid"]:
                return result(S3)
            continue

        action = parsed.action
        if action.name == "finish":
            recorder.action(step=step, name="finish", args={}, status=EXECUTED, message="", duration_ms=0.0)
            return result(S1)

        t0 = time.perf_counter()
        try:
            outcome = pipeline.execute(action)
        except Exception as e:
            outcome = None
            detail = f"execute failed: {e}"
        duration = (time.perf_counter() - t0) * 1000
        if outcome is None or outcome.status == ERROR:
            message = detail if outcome is None else outcome.message
            recorder.action(step=step, name=action.name, args=action.args, status=ERROR, message=message,
                            duration_ms=duration)
            return result(S5, message)
        recorder.action(step=step, name=action.name, args=action.args, status=outcome.status,
                        message=outcome.message or outcome.detail, duration_ms=duration)
        history.add_action(step, action, outcome)
        consecutive_invalid = consecutive_invalid + 1 if outcome.status == INVALID else 0
        if outcome.status == INVALID and consecutive_invalid >= limits["max_consecutive_invalid"]:
            return result(S3)
        assert outcome.status in (EXECUTED, REJECTED, INVALID)
