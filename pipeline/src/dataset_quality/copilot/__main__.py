"""Runs the Copilot's HTTP layer (`http_app.py`) with uvicorn.

Invoked as ``python -m dataset_quality.copilot`` from the ``copilot`` service
in docker-compose.yml (its own service, started by plain ``docker compose
up`` -- not gated behind the ``pipeline`` Compose profile, which is CLI/batch
DVC tooling and a separate concern from this always-on HTTP service).
"""

from __future__ import annotations

from pathlib import Path

import uvicorn

from dataset_quality.config.settings import get_settings
from dataset_quality.copilot.agent import tool_specs_from_server
from dataset_quality.copilot.http_app import build_app
from dataset_quality.copilot.providers import AnthropicProvider
from dataset_quality.copilot.server import build_server


def main() -> None:
    settings = get_settings()
    server = build_server(Path(settings.copilot_contracts_dir))
    tool_specs = tool_specs_from_server(server)

    def provider_factory() -> AnthropicProvider:
        # Raises ValueError when ANTHROPIC_API_KEY isn't set -- build_app
        # catches that per-request and answers with a clean 503, rather than
        # this process refusing to start at all (see http_app.py).
        return AnthropicProvider.from_settings(
            api_key=settings.anthropic_api_key, model=settings.copilot_model
        )

    app = build_app(server=server, provider_factory=provider_factory, tool_specs=tool_specs)
    uvicorn.run(app, host="0.0.0.0", port=settings.copilot_port)


if __name__ == "__main__":
    main()
