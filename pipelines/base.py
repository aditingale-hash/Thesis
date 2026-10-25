"""Common interface of the three interaction pipelines.

The agent loop only talks to this interface, so task, model, prompt, loop, stopping
conditions, verification and measurement are identical in all conditions and only
the representation (observation + action space) differs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# Action result statuses
EXECUTED = "executed"   # performed and accepted
REJECTED = "rejected"   # performed but refused by a business rule (message = core error text)
INVALID = "invalid"     # cannot be performed at interface level (unknown ref, bad args, off-screen target)
ERROR = "error"         # infrastructure problem (browser crash, shop down) -> S5


@dataclass
class Observation:
    """What the agent perceives before one step.

    ``content`` is the text observation or the base64 PNG screenshot. ``size`` is
    characters for text and bytes for PNG. ``prompt_text`` is what goes into prompt
    section 5 (for images a short caption; the image is attached to the message).
    """

    modality: str                       # "text" | "image"
    content: str
    size: int
    prompt_text: str


@dataclass
class Action:
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class ActionResult:
    status: str                         # EXECUTED | REJECTED | INVALID | ERROR
    message: str = ""                   # error / rejection text shown in the agent's history
    summary: str = ""                   # short label for the history line, e.g. 'page "Cart"'
    detail: str = ""                    # trace only, never shown to the agent (e.g. the notice text
                                        # read from the DOM for the visual pipeline's statistics)


@dataclass
class RunSession:
    """Everything a pipeline needs to connect to the shop for one run."""

    base_url: str
    cookie_name: str
    cookie_value: str
    browser: object = None              # Playwright Browser (browser pipelines only)
    run_dir: object = None              # Path for screenshots (visual pipeline)


# An action spec maps action name -> {argument: (json type, required)}; json type in
# {"integer", "number", "string"}. Every pipeline accepts finish().
FINISH_SPEC = {"finish": {}}


class InteractionPipeline(ABC):
    """One interaction approach (DOM, visual or tool)."""

    name: str = ""

    @abstractmethod
    def attach(self, session) -> None:
        """Connect to the shop for one run (``session``: base_url, cookie, browser, run_dir)."""

    @abstractmethod
    def action_space(self) -> str:
        """Text for prompt section 2."""

    @abstractmethod
    def action_specs(self) -> dict:
        """Action names and argument types, used by the action parser (includes finish)."""

    @abstractmethod
    def observe(self) -> Observation:
        """Current observation."""

    @abstractmethod
    def execute(self, action: Action) -> ActionResult:
        """Perform one (already parsed) action."""

    def argument_values(self) -> dict:
        """Allowed values of arguments with a fixed list, as {action: {argument: [values]}} (default none)."""
        return {}

    def response_schema(self) -> dict:
        """JSON schema of a valid response in this pipeline, given to the model runtime as structured output.

        The format is the common {"thought", "action", "args"}; the schema restricts "action" to this
        pipeline's action names and "args" to exactly the arguments (types, required, fixed values) of
        the chosen action. Built only from ``action_specs`` and ``argument_values``.
        """
        values = self.argument_values()
        variants = []
        for name, spec in self.action_specs().items():
            properties = {}
            for arg, (json_type, _) in spec.items():
                properties[arg] = {"type": json_type}
                if arg in values.get(name, {}):
                    properties[arg]["enum"] = list(values[name][arg])
            variants.append({
                "type": "object",
                "properties": {
                    "thought": {"type": "string"},
                    "action": {"type": "string", "enum": [name]},
                    "args": {"type": "object", "properties": properties,
                             "required": [a for a, (_, required) in spec.items() if required],
                             "additionalProperties": False},
                },
                "required": ["thought", "action", "args"],
            })
        return {"anyOf": variants}

    def truncate(self, observation: Observation, max_chars: int) -> str:
        """Shorten the text observation to ``max_chars``; pipelines override with their own rule."""
        return observation.prompt_text[:max_chars]

    def close(self) -> None:
        """Release browser contexts / HTTP clients."""
