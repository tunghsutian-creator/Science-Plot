"""Run the packaged first-figure test through a real, isolated Codex client."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from distribution.macos.mcp_probe import read_connection, verify_first_figure


async def verify_codex(codex: Path, connection_directory: Path, command: Path, output: Path) -> dict:
    read_connection(connection_directory, command)
    with TemporaryDirectory(prefix="sciplot-codex-") as temporary:
        home = Path(temporary).resolve()
        (home / "config.toml").write_bytes((connection_directory / "codex-mcp.toml").read_bytes())
        env = {key: os.environ[key] for key in ("HOME", "PATH", "TMPDIR") if key in os.environ}
        env.update(CODEX_HOME=str(home), QT_QPA_PLATFORM="offscreen", OPENAI_BASE_URL="http://127.0.0.1:9/v1")
        child = await asyncio.create_subprocess_exec(
            str(codex.resolve()), "app-server", "--stdio", "--strict-config", cwd=home, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, limit=4 << 20,
        )
        assert child.stdin is not None and child.stdout is not None
        request = 0

        async def send(message: dict) -> None:
            child.stdin.write(json.dumps(message).encode() + b"\n")
            await child.stdin.drain()

        async def rpc(method: str, params: dict) -> dict:
            nonlocal request
            request += 1
            await send({"id": request, "method": method, "params": params})
            async with asyncio.timeout(305):
                while line := await child.stdout.readline():
                    response = json.loads(line)
                    if response.get("id") == request:
                        if "error" in response:
                            raise RuntimeError(f"{method}: {response['error']}")
                        return response["result"]
            raise RuntimeError(f"Codex exited before answering {method}")

        try:
            identity = await rpc("initialize", {"clientInfo": {"name": "sciplot_smoke", "version": "1"}})
            if Path(identity["codexHome"]).resolve() != home:
                raise RuntimeError("Codex did not use the isolated configuration")
            await send({"method": "initialized"})
            session = await rpc("thread/start", {"cwd": str(home), "ephemeral": True})
            thread = session["thread"]

            async def call(tool: str, arguments: dict) -> dict:
                result = await rpc("mcpServer/tool/call", {
                    "threadId": thread["id"], "server": "sciplot", "tool": tool, "arguments": arguments,
                })
                payload = result.get("structuredContent")
                if result.get("isError") or not isinstance(payload, dict):
                    raise RuntimeError(f"{tool} failed: {result.get('content')}")
                return payload

            capabilities = await call("sciplot_capabilities", {})
            if capabilities.get("transport") != "mcp_stdio" or capabilities.get("model_configuration_required") is not False:
                raise RuntimeError("Codex did not connect to the bundled local SciPlot server")
            result = await verify_first_figure(
                call, output, claim="actual_codex_app_server_scripted_first_figure_without_model_turn",
            )
            return {**result, "codex_version": thread["cliVersion"], "transport": "mcp_stdio"}
        finally:
            child.stdin.close()
            try:
                await asyncio.wait_for(child.wait(), timeout=5)
            except TimeoutError:
                child.kill()
                await child.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("codex", "connection-directory", "command", "output"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify_codex(args.codex, args.connection_directory, args.command, args.output))))


if __name__ == "__main__":
    main()
