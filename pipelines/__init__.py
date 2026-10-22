"""The three interaction pipelines."""

PIPELINES = ("dom", "visual", "tool")


def make_pipeline(name: str, model_config: dict | None = None):
    """Create a pipeline by name ("dom", "visual" or "tool")."""
    model_config = model_config or {}
    if name == "dom":
        from pipelines.dom import DomPipeline
        return DomPipeline()
    if name == "visual":
        from pipelines.visual import VisualPipeline
        return VisualPipeline(model_config.get("coordinate_mode", "pixels"), model_config.get("perception", "none"))
    if name == "tool":
        from pipelines.tool import ToolPipeline
        return ToolPipeline()
    raise ValueError(f"unknown pipeline {name}")
