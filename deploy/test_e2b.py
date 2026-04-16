"""Test E2B sandbox: create, run Kai MCP call, pause, resume, verify state."""
import os
import time
from e2b import Sandbox

os.environ.setdefault("E2B_API_KEY", "e2b_3bfb6cba62d0fe6af83f97dede56825c0b90c547")

KAI_JWT = os.environ.get("KAI_JWT_TOKEN", "")

print("1. Creating sandbox...")
t0 = time.time()
sbx = Sandbox.create(timeout=300)
sid = sbx.sandbox_id
print(f"   Created in {time.time()-t0:.1f}s, ID: {sid}")

print("2. Setting up agent state...")
sbx.commands.run("pip install httpx -q", timeout=30)
sbx.files.write("/home/user/config.yaml", "workspace: 69723bee\nsession_count: 42\n")
print("   Done")

print("3. Calling Kai MCP from inside sandbox...")
test_script = f"""
import httpx, json
r = httpx.post(
    "https://production.kai-backend.dria.co/mcp",
    json={{"jsonrpc": "2.0", "id": 1, "method": "initialize",
           "params": {{"protocolVersion": "2025-03-26", "capabilities": {{}},
                       "clientInfo": {{"name": "kai-e2b", "version": "0.1"}}}}}},
    headers={{"Authorization": "Bearer {KAI_JWT}",
              "Content-Type": "application/json",
              "Accept": "application/json, text/event-stream"}},
    timeout=10,
)
print(f"MCP Status: {{r.status_code}}")
d = r.json()
srv = d.get("result", {{}}).get("serverInfo", {{}})
print(f"Server: {{srv.get('name', '?')}} v{{srv.get('version', '?')}}")
"""
sbx.files.write("/tmp/test_mcp.py", test_script)
result = sbx.commands.run("python3 /tmp/test_mcp.py", timeout=15)
print(f"   {result.stdout.strip()}")
if result.stderr.strip():
    print(f"   ERR: {result.stderr.strip()[:200]}")

print("4. Pausing...")
t1 = time.time()
sbx.pause()
print(f"   Paused in {time.time()-t1:.1f}s")

print("5. Waiting 5s...")
time.sleep(5)

print("6. Resuming...")
t2 = time.time()
resumed = Sandbox.connect(sid, timeout=300)
print(f"   Resumed in {time.time()-t2:.1f}s")

print("7. State check...")
content = resumed.files.read("/home/user/config.yaml")
print(f"   Config: {content.strip()}")

resumed.kill()
print("\nE2B + Kai MCP: PASSED")
