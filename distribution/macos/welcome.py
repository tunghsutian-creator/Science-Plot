"""A local, read-only connection guide; never installs an AI configuration."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import subprocess
import tempfile
from pathlib import Path


def connection_files(command: Path) -> dict[str, str]:
    path = str(command.resolve())
    return {
        "codex-mcp.toml": (
            "# 供审阅后手工添加；SciPlot 不会修改你的 Codex 配置。\n"
            "[mcp_servers.sciplot]\n"
            f"command = {json.dumps(path, ensure_ascii=False)}\n"
            'args = ["mcp"]\n'
            "startup_timeout_sec = 30\n"
            "tool_timeout_sec = 300\n"
        ),
        "mcp-server.json": json.dumps(
            {"mcpServers": {"sciplot": {"command": path, "args": ["mcp"]}}},
            ensure_ascii=False, indent=2,
        ) + "\n",
    }


def render_page(command: Path, doctor: dict, mcp_available: bool, status_path: Path, build: dict | None = None) -> str:
    ready = doctor.get("status") == "ready"
    status = "本地环境已就绪" if ready else "本地环境需要处理"
    failures = [str(item.get("detail", item.get("label", ""))) for item in doctor.get("checks", []) if item.get("status") == "failed" and item.get("required")]
    if not ready and not failures:
        failures.append(str(doctor.get("error", "请查看环境检查记录。")))
    command_text = html.escape(str(command.resolve()))
    build = build or {}
    architecture = "Apple silicon" if build.get("architecture") == "arm64" else str(build.get("architecture", "当前架构"))
    platform_note = html.escape(f"构建平台：macOS {build.get('build_macos', '当前版本')} · {architecture}")
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SciPlot · 开始使用</title>
<style>body{{font:17px/1.75 -apple-system,BlinkMacSystemFont,sans-serif;color:#203037;background:#f5f8f8;margin:0}}main{{max-width:840px;margin:48px auto;padding:0 24px 64px}}h1{{font-size:36px;line-height:1.3}}h2{{font-size:23px;margin-top:32px}}.card{{background:white;border:1px solid #dbe4e5;border-radius:14px;padding:20px 26px;margin:18px 0}}.status{{color:{'#146b50' if ready else '#a44315'};font-weight:700}}code,pre{{font:14px/1.5 ui-monospace,monospace;overflow-wrap:anywhere;white-space:pre-wrap}}a{{color:#006f85}}button{{font:inherit;border:1px solid #bbcdd0;border-radius:8px;background:#eef6f6;padding:8px 16px;cursor:pointer}}small{{color:#66777d}}li{{margin:10px 0}}</style>
<main><small>SCIPLOT · 本地科研绘图</small><h1>把文件交给 AI，<br>让 SciPlot 在本机完成绘图。</h1><small>{platform_note}</small>
<div class="card"><span class="status">{status}</span>
<p>{'Python、Qt 和 Veusz 随应用提供，无需另外安装。' if ready else html.escape('；'.join(failures))}</p>
<a href="{status_path.name}">查看本次环境检查</a></div>
<h2>1. 放好应用，再连接一次</h2>
<p>把完整的 SciPlot.app 放在一个固定位置，再双击它打开本页。只移动整个应用，不拆开包内文件。移动后，重新打开本页并更新 AI 工具的连接路径。旧交付的打开命令可能仍指向应用的原位置；请先用更新后的 AI 连接继续原项目并重新导出。</p>
<p>{'MCP 本地服务入口可用。' if mcp_available else '当前构建尚未提供 MCP 入口；请先使用下面的公开 CLI 路径，或取得包含 MCP 的构建。'}</p>
<p>在支持本地 MCP 的 AI 工具里添加 <b>STDIO</b> 服务：名称 <b>sciplot</b>，命令填下方路径，参数填 <b>mcp</b>。</p>
<div class="card"><code id="command">{command_text}</code><p><button onclick="copyCommand()">复制命令路径</button> <span id="copyStatus" role="status"></span></p></div>
<p>Codex 可在设置中的 MCP servers 添加服务器；也可由你审阅后将下列片段加入配置。这里不会改写任何 AI 工具的设置。</p>
<p><a href="codex-mcp.toml" download>下载 Codex 配置片段</a> · <a href="mcp-server.json" download>下载通用 MCP JSON</a> · <a href="https://learn.chatgpt.com/docs/extend/mcp?surface=cli">官方连接说明</a></p>
<h2>2. 在 AI 对话里给文件和需求</h2>
<div class="card">用 SciPlot 把这些 DSC 数据画成图。样品名称保持原样，给我可编辑项目、PDF 和 300 dpi TIFF；只有科学含义不明确时再问我。</div>
<p>AI 负责理解需求；本地 SciPlot 检查数据、生成图稿和交付文件。你只需回答真实歧义，例如工作表、单位或样品对应关系。不要为了继续运行而猜缺失的实验信息。</p>
<h2>3. 看首图，再用一句话修改</h2>
<div class="card">把这张图的纵轴标题字号改大一点，给我看修改后的预览，并导出成图。</div>
<p>当前可用修改以 AI 查询到的能力为准。高级手工编辑可打开交付包里的 Open_in_Veusz.command；保存并关闭同项目窗口后，再让 AI 继续修改。首次确认页面和结果页只承担导入确认与结果查看。</p>
<h2>4. 找到结果，下次接着做</h2>
<p>交付包默认在原数据旁的 <b>文件名_SciPlot</b> 文件夹，含 PDF、TIFF、CSV 和可编辑 VSZ。下次把同一个文件夹交给 AI，说“继续这个项目”，无需重新导入。</p>
<p>原位置的打开命令会继续受管项目；复制或移动后的交付包打开独立快照。应用缺失、图稿有新修改或文件已变化时，请让 AI 读取实际诊断再恢复。</p>
<details><summary>构建与验收范围</summary><p>这是当前 macOS 架构的本地分发构建，含依赖与动态库搬移审计。未使用 Developer ID 签名，未公证；二进制的 ad-hoc 签名不代表身份认证。干净 Mac 安装、其它 macOS 版本和真实小白测试仍需独立验收。不要把本机 doctor 成功当作这些验收已经通过。</p><p>本页只检查环境，不启动付费模型。文件内容是否发送给模型由你使用的外部 AI 工具决定。</p></details>
</main><script>function copyCommand(){{const s=document.getElementById('copyStatus');if(navigator.clipboard){{navigator.clipboard.writeText(document.getElementById('command').textContent).then(()=>s.textContent='已复制').catch(()=>s.textContent='请选中上方路径复制');}}else{{s.textContent='请选中上方路径复制';}}}}</script></html>'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    resources = Path(__file__).resolve().parent
    command = resources.parent / "MacOS" / "sciplot"
    token = hashlib.sha256(str(command).encode()).hexdigest()[:16]
    out = args.out or Path(tempfile.gettempdir()) / "SciPlot-connection" / token
    out.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(command), "doctor", "--json"], capture_output=True, text=True, timeout=60)
    try:
        doctor = json.loads(result.stdout)
    except json.JSONDecodeError:
        doctor = {"status": "needs_fix", "error": result.stderr or result.stdout}
    status_path = out / "environment-check.json"
    status_path.write_text(json.dumps(doctor, ensure_ascii=False, indent=2) + "\n")
    help_result = subprocess.run([str(command), "--help"], capture_output=True, text=True, timeout=30)
    mcp_available = "mcp" in help_result.stdout.split("positional arguments:")[0]
    for name, content in connection_files(command).items():
        (out / name).write_text(content, encoding="utf-8")
    page = out / "开始使用.html"
    manifest_path = resources / "build-manifest.json"
    build = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    page.write_text(render_page(command, doctor, mcp_available, status_path, build), encoding="utf-8")
    if not args.no_open:
        subprocess.run(["/usr/bin/open", str(page)], check=True)
    print(json.dumps({"page": str(page), "doctor_status": doctor.get("status"), "mcp_available": mcp_available}, ensure_ascii=False))
    return 0 if doctor.get("status") == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
