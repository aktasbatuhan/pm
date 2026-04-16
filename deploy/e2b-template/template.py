from e2b import Template, wait_for_port

template = (
    Template()
    .from_python_image("3.11")
    # System deps
    .apt_install(["git", "curl", "build-essential"])
    # Node.js 20 (for MCP tools that use npx)
    .run_cmd("curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y nodejs")
    # Copy agent code
    .copy("../../", "/home/user/kai-agent")
    # Install Python deps
    .run_cmd("cd /home/user/kai-agent && pip install --no-cache-dir -r requirements.txt")
    .pip_install(["e2b", "httpx", "mcp>=1.26.0", "slack-bolt", "slack-sdk"])
    # Create config directory
    .run_cmd("mkdir -p /home/user/.kai-agent/sessions /home/user/.kai-agent/memories")
    # Default config
    .copy("default-config.yaml", "/home/user/.kai-agent/config.yaml")
    # Link skills
    .run_cmd("ln -sf /home/user/kai-agent/skills /home/user/.kai-agent/skills")
    # Chat server
    .copy("kai_chat_server.py", "/home/user/kai_chat_server.py")
    # Set working directory
    .set_workdir("/home/user")
    # Start command: launches chat server on port 8080
    .set_start_cmd("python3 /home/user/kai_chat_server.py", wait_for_port(8080))
)
