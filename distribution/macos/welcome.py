"""A local, read-only connection guide; never installs an AI configuration."""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import shlex
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote


DAILY_MCP_ARGS = ("mcp", "--profile", "daily")
FIRST_FIGURE_NAME = "SciPlot-first-figure.csv"
FIRST_FIGURE_CSV = """Time,Mass,Weight,Time,Mass,Weight
s,%,%,s,%,%
Sample A,Sample A,Sample A,Sample B,Sample B,Sample B
0,100,99,0,100,98
10,98,96,10,97,95
20,95,93,20,92,89
30,91,89,30,86,83
40,90,87,40,82,78
"""


def feedback_report(doctor: dict, build: dict, mcp_available: bool) -> dict:
    """Export an allowlisted diagnostic summary, not paths, logs or data."""
    known_checks = {
        "python_version", "veusz_vendor", "pyqt6", "veusz_qt_runtime", "vsz_lifecycle",
        "publication_foundation", "style_template_contract", "publication_layout_inventory",
        "skill_wrapper", "ready_rules", "validated_envelopes", "ready_rule_fixtures", "repo_root",
    }
    return {
        "kind": "sciplot_beta_feedback", "version": 1,
        "build": {key: build.get(key) for key in (
            "app_version", "architecture", "build_macos", "source_snapshot_sha256",
        )},
        "doctor_status": doctor.get("status") if doctor.get("status") in {"ready", "needs_fix"} else "unknown",
        "mcp_available": mcp_available,
        "checks": [
            {"id": item["id"], "status": item["status"]}
            for item in doctor.get("checks", []) if isinstance(item, dict)
            and item.get("id") in known_checks and item.get("status") in {"passed", "failed", "skipped"}
        ],
        "included": "build identity and environment check states only",
        "excluded": "source files, measurements, sample names, file paths, error text, AI configuration and credentials",
    }


def run_json(arguments: list[str], *, timeout: int) -> dict:
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("检查结果不是 JSON 对象")
        if result.returncode:
            return {"status": "needs_fix", "error": result.stderr or "环境检查未通过", "checks": payload.get("checks", [])}
        return payload
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return {"status": "needs_fix", "error": str(error)}


def connection_files(command: Path) -> dict[str, str]:
    path = str(command.resolve())
    return {
        "codex-mcp.toml": (
            "# 供审阅后手工添加；SciPlot 不会修改你的 Codex 配置。\n"
            "[mcp_servers.sciplot]\n"
            f"command = {json.dumps(path, ensure_ascii=False)}\n"
            f"args = {json.dumps(DAILY_MCP_ARGS)}\n"
            "startup_timeout_sec = 30\n"
            "tool_timeout_sec = 300\n"
        ),
        "mcp-server.json": json.dumps(
            {"mcpServers": {"sciplot": {"command": path, "args": list(DAILY_MCP_ARGS)}}},
            ensure_ascii=False, indent=2,
        ) + "\n",
    }


def render_page(command: Path, doctor: dict, mcp_available: bool, status_path: Path, build: dict | None = None) -> str:
    ready = doctor.get("status") == "ready"
    status = "本地环境已就绪" if ready else "本地环境需要处理"
    failures = [str(item.get("detail", item.get("label", ""))) for item in doctor.get("checks", []) if item.get("status") == "failed" and item.get("required")]
    if not ready and not failures:
        failures.append(str(doctor.get("error", "请查看环境检查记录。")))
    command_path = str(command.resolve())
    command_text = html.escape(command_path)
    build = build or {}

    def cli(*arguments: str) -> str:
        return html.escape(shlex.join([command_path, *arguments]))

    configurations = connection_files(command)
    codex_download = "data:text/plain;charset=utf-8," + quote(configurations["codex-mcp.toml"], safe="")
    mcp_download = "data:application/json;charset=utf-8," + quote(configurations["mcp-server.json"], safe="")
    example_download = "data:text/csv;charset=utf-8," + quote(FIRST_FIGURE_CSV, safe="")
    feedback_download = "data:application/json;charset=utf-8," + quote(
        json.dumps(feedback_report(doctor, build, mcp_available), ensure_ascii=False, indent=2) + "\n", safe="",
    )
    architecture = "Apple silicon" if build.get("architecture") == "arm64" else str(build.get("architecture", "当前架构"))
    platform_note = html.escape(f"版本 {build.get('app_version', '未知')} · macOS {build.get('build_macos', '当前版本')} · {architecture}")
    mcp_setup = (
        f'''<p>在支持本地 STDIO MCP 的 AI 客户端添加名为 <b>sciplot</b> 的服务。命令填上方路径，三个参数分别是 <code>{"</code>、<code>".join(DAILY_MCP_ARGS)}</code>。<code>daily</code> 包含日常建图、找回、编辑与导出；需要完整工具目录时，把 <code>daily</code> 改成 <code>expert</code> 后重新连接。</p>
<p><b>本机检测到 MCP 入口；你的 AI 客户端尚未验证。</b> 添加配置后，在实际客户端发送「请调用 SciPlot 的 <code>sciplot_capabilities</code>，告诉我调用是否成功。」看到实际工具调用和返回的 <code>mcp_stdio</code> 才算连通；仅看到工具名称或 AI 说「已连接」不算。这里不会自动连接或修改设置。</p>
<p><a href="{codex_download}" download="codex-mcp.toml">下载 Codex 配置片段</a> · <a href="{mcp_download}" download="mcp-server.json">下载通用 MCP JSON</a> · <a href="https://learn.chatgpt.com/docs/extend/mcp?surface=cli">官方连接说明</a></p>'''
        if mcp_available else
        "<p>当前构建尚未提供 MCP 入口。若本地环境已就绪，可用下方命令行；也可向维护者取得支持 MCP 的构建。</p>"
    )
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SciPlot · 开始使用</title>
<style>body{{font:17px/1.75 -apple-system,BlinkMacSystemFont,sans-serif;color:#203037;background:#f5f8f8;margin:0}}main{{max-width:840px;margin:48px auto;padding:0 24px 64px}}h1{{font-size:36px;line-height:1.3}}h2{{font-size:23px;margin-top:32px}}.card{{background:white;border:1px solid #dbe4e5;border-radius:14px;padding:20px 26px;margin:18px 0}}.status{{color:{'#146b50' if ready else '#a44315'};font-weight:700}}code,pre{{font:14px/1.5 ui-monospace,monospace;overflow-wrap:anywhere;white-space:pre-wrap}}a{{color:#006f85}}button{{font:inherit;border:1px solid #bbcdd0;border-radius:8px;background:#eef6f6;padding:8px 16px;cursor:pointer}}small{{color:#66777d}}li{{margin:10px 0}}</style>
<main><small>SCIPLOT · 本地科研绘图</small><h1>把文件交给 AI，<br>让 SciPlot 在本机完成绘图。</h1><small>{platform_note}</small>
<div class="card"><span class="status">{status}</span>
<p>{'Python、Qt 和 Veusz 随应用提供，无需另外安装。' if ready else html.escape('；'.join(failures))}</p>
<a href="{status_path.name}">查看本次环境检查</a></div>
<h2>1. 放好应用，连接你的 AI</h2>
<p>把整个 SciPlot.app 放在固定位置（例如“应用程序”），双击后点击「打开 AI 连接指南」即可回到本页。移动应用后，重新打开本页，并用新路径更新客户端连接。</p>
<div class="card"><code id="command">{command_text}</code><p><button onclick="copyCommand()">复制命令路径</button> <span id="copyStatus" role="status"></span></p></div>
{mcp_setup}
<h2>2. 先用安全示例画第一张图</h2>
<p><a href="{example_download}" download="{FIRST_FIGURE_NAME}">下载双样品练习 CSV</a>。这是合成数据，不含任何实验记录。将它保存在你愿意保留的文件夹，连接后把本机文件路径交给 AI，再发送下面这段话。</p>
<div class="card">用 SciPlot 把这个 CSV 的 Sample A 和 Sample B 画在同一张质量–时间图上。按原始数据叠画，不做归一化；先向我确认选哪一列作为纵轴，不要代我选。完成后给我看图，给我 PDF、300 dpi TIFF 和可继续编辑的项目路径。</div>
<p>两列都以百分比记录，但数值不同。客户端应先让你在 <code>Mass</code> 和 <code>Weight</code> 之间选，再继续同一次任务。练习可答「用 Mass」；不用填写任何内部编号。检查图中有两个样品、横轴为秒、纵轴为百分比，再打开实际导出的文件。</p>
<p>换成自己的原始文件时，只有影响结果的样品、工作表、列或单位不明确才需要确认。以任务返回的路径为准：交付目录通常在原数据旁，包含 PDF、TIFF、绘图 CSV 和 VSZ。保留原始文件和返回的<strong>可续编项目路径</strong>；交付文件和项目各自保留，不要把导出的 VSZ 当成原项目。</p>
<h2>3. 下次找回原图，再预览修改</h2>
<div class="card">继续这个 SciPlot 项目，不要重新建图。把图例里 Sample A 的显示名改成 Practice A，原始数据不变。先给我看候选图，确认后再保存和更新交付。</div>
<p>把原项目路径或原位置的已登记交付目录交给 AI。它用 <code>sciplot_project_open</code> 识别图；只记得原始文件时，先用 <code>sciplot_task_continue</code> 查找已有项目，有多个候选时由你选择。不要用原输入再建一份来代替编辑。</p>
<p>可编辑图按实际公布的能力用 <code>sciplot_task_edit</code> 等入口提交修改。看过候选图再确认保存和导出。如果已保存但导出失败，修正原因后用原任务重试，不要再应用一次修改。</p>
<p><strong>交稿：</strong>让 AI 给你当前的 PDF 或论文交付包，交出去的是成果快照。<strong>搬家续编：</strong>让 AI「把整个项目迁到新位置」，先导出项目迁移包，再导入一个未用的目录，保留同一项目和历史；以后从返回的新路径继续，不要两边同时改。<strong>另存副本：</strong>让 AI「把当前这张图另存为独立副本」，在新目录单独编辑；原图不变，也不会带过去旧项目的历史。</p>
<p>如果打开结果为 <code>read_only</code>，旧图可读取，并用 <code>sciplot_project_legacy_redraw</code> 原样重画到新目录。只有要用新编辑功能时，才按返回的 <code>sciplot_project_legacy_convert</code> 指引将受支持的 XY 图转换为独立 Managed 副本；原图不变，不支持的图不强行转换。历史启动文件不作为打开入口。</p>
<details><summary>不接入 AI 时的命令行入口</summary>
<p>将示例中的绝对路径换成自己的路径。出图：</p><pre>{cli("task", "create", "/absolute/original.csv", "--json")}</pre>
<p>查看已保存图的身份和可用操作：</p><pre>{cli("plot", "open", "/absolute/saved-project", "--json")}</pre>
<p>按返回的 <code>next_step</code> 继续同一个任务；不要编造决策 ID 或接受没看过的预览。</p></details>
<h2>遇到问题时</h2><p>记录刚才的操作、预期结果和实际现象，并附上<a href="{feedback_download}" download="SciPlot-feedback.json">本机检查摘要</a>。摘要仅包含版本、构建编号和检查状态，不包含实验数据、样品名称、文件路径、错误全文或 AI 密钥；不会自动发送。完整环境检查仅供你在本机查看。</p>
<details><summary>构建与验收范围</summary><p>当前包的签名与公证状态以维护者提供的 release.json 为准；只有 public 渠道并通过发行检查的包才供公开分发。candidate 包用于本地候选验证。本机 Doctor、合成原生导出和 MCP 工具发现分别检查环境、渲染和协议；不能替代干净 Mac 安装、其它系统或架构的兼容性、真实 AI 客户端的连接与任务，或独立用户试用。</p><p>本页只检查环境，不启动付费模型。文件内容是否发送给模型由你使用的外部 AI 工具决定。</p></details>
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
    doctor = run_json([str(command), "doctor", "--json"], timeout=60)
    status_path = out / "environment-check.json"
    status_path.write_text(json.dumps(doctor, ensure_ascii=False, indent=2) + "\n")
    capabilities = run_json([str(command), "task", "capabilities", "--json"], timeout=30)
    mcp_available = (
        importlib.util.find_spec("mcp") is not None
        and capabilities.get("kind") == "sciplot_task_capabilities"
        and bool(capabilities.get("contract_sha256"))
    )
    for name, content in connection_files(command).items():
        (out / name).write_text(content, encoding="utf-8")
    page = out / "开始使用.html"
    manifest_path = resources / "build-manifest.json"
    build = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    (out / "feedback.json").write_text(json.dumps(feedback_report(doctor, build, mcp_available), ensure_ascii=False, indent=2) + "\n")
    page.write_text(render_page(command, doctor, mcp_available, status_path, build), encoding="utf-8")
    if not args.no_open:
        subprocess.run(["/usr/bin/open", str(page)], check=True)
    print(json.dumps({"page": str(page), "doctor_status": doctor.get("status"), "mcp_available": mcp_available}, ensure_ascii=False))
    return 0 if doctor.get("status") == "ready" and mcp_available else 1


if __name__ == "__main__":
    raise SystemExit(main())
