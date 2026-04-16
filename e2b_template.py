from e2b import Template

template = (
    Template()
    .from_dockerfile("e2b.Dockerfile")
    # Set working directory to agent root so uv can find pyproject.toml + .venv
    .set_workdir("/home/user/kai-agent")
    # No start_cmd — the backend writes runtime env vars then launches the server
    # via sandbox.commands.run() so it inherits the correct environment.
)
