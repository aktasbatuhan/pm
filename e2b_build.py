"""Build E2B template for kai-agent. Run from repo root."""

import os
import re

from e2b import Template, default_build_logger
from e2b_template import template

template_name = os.getenv("E2B_TEMPLATE_NAME", "kai-agent")

# Read version from pyproject.toml
with open("pyproject.toml") as f:
    version = re.search(r'version\s*=\s*"(.+?)"', f.read()).group(1)

# Embed version in name (dots → dashes since E2B names don't allow dots)
# e.g. kai-agent-v0-3-0
build_name = f"{template_name}-v{version.replace('.', '-')}"

print(f"Building E2B template: {build_name}")

result = Template.build(
    template,
    build_name,
    cpu_count=2,
    memory_mb=4096,
    on_build_logs=default_build_logger(),
)

print("\nTemplate built successfully!")
print(f"Template ID: {result.template_id}")
print(f"Version: {version}")
print("Save this ID — you'll need it for the backend E2B_AGENT_TEMPLATE env var.")
