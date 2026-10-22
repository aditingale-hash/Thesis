"""Build the prompt from the five-section template.

Sections: 1 role and rules, 2 action space, 3 task, 4 history (one line per previous
step), 5 current observation. Previous observations are never repeated. If the
prompt would exceed the context budget, the current text observation is truncated
by the pipeline's own rule and the step is marked ``truncated``.
"""

from pathlib import Path

TEMPLATE = (Path(__file__).with_name("prompt_template.txt")).read_text(encoding="utf-8")

# Rough token estimate for budgeting (no tokenizer for every model): 1 token ~ 3.5 characters.
CHARS_PER_TOKEN = 3.5
# Budget for a 1280x800 screenshot in the prompt (Qwen2.5-VL: 28x28 pixel patches -> ~1,300 tokens).
IMAGE_TOKEN_ESTIMATE = 1400


def render(action_space: str, instruction: str, history: list[str], observation: str) -> str:
    """Fill the template."""
    return (TEMPLATE
            .replace("{action_space}", action_space)
            .replace("{instruction}", instruction)
            .replace("{history}", "\n".join(history) if history else "(no previous steps)")
            .replace("{observation}", observation))


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def build_prompt(pipeline, observation, instruction: str, history: list[str], model_config: dict) -> tuple[str, bool]:
    """Return ``(prompt, truncated)`` for the current step."""
    budget = model_config["num_ctx"] - model_config["max_output_tokens"]
    if observation.modality == "image":
        budget -= IMAGE_TOKEN_ESTIMATE
    text = observation.prompt_text
    prompt = render(pipeline.action_space(), instruction, history, text)
    if estimate_tokens(prompt) <= budget:
        return prompt, False
    overflow_chars = int((estimate_tokens(prompt) - budget) * CHARS_PER_TOKEN) + 1
    text = pipeline.truncate(observation, max(0, len(text) - overflow_chars))
    return render(pipeline.action_space(), instruction, history, text), True
