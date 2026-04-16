#!/usr/bin/env python3
"""Build the Kai Agent E2B template."""
import os
import sys

# Add template dir to path so we can import template.py
sys.path.insert(0, os.path.dirname(__file__))

from e2b import Template, default_build_logger
from template import template

if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "kai-agent"
    print(f"Building E2B template: {tag}")
    result = Template.build(
        template,
        tag,
        cpu_count=2,
        memory_mb=2048,
        on_build_logs=default_build_logger(),
    )
    print(f"Template built: {result}")
