#!/usr/bin/env python3
"""
一键更新软路由 OpenClash 配置（绕过卡顿的 Web UI）。

完整链路（与你现有订阅一致）：
  MonoProxy → generate_proxy_nodes.py
           → scp ss.json  →  软路由 /www/luci-static/resources/ss.json
           → subconverter :25500  +  ACL4SSR_Online_Full_self.ini（规则）
           → self-github-ssr-V1.yaml
           → scp 到 /etc/openclash/config/
           → 重启 OpenClash 并健康检查

用法（在仓库根目录）：
  # 最常用：从 MonoProxy 重新生成节点 → 推送 → 拉订阅 → 写配置 → 重启
  python3 Tool/update_openclash.py

  # 只更新订阅/规则（ss.json 已是最新，不重跑 MonoProxy）
  python3 Tool/update_openclash.py --skip-generate

  # 只生成并推送 ss.json，不碰 OpenClash yaml
  python3 Tool/update_openclash.py --nodes-only

  # 干跑：生成+转换，写本地文件，不 scp / 不重启
  python3 Tool/update_openclash.py --dry-run

  # 只用 500G 套餐节点
  python3 Tool/update_openclash.py --service 108324

  # 指定路由器 SSH 别名 / LAN IP
  python3 Tool/update_openclash.py --router-host istore --router-ip 192.168.0.1

依赖：
  - Mac 上能 ssh/scp 到软路由（~/.ssh/config 别名 + 密钥登录）
  - 软路由上 subconverter 监听 :25500（docker 或本机均可）
  - 软路由上 OpenClash 已安装
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults（按你当前环境）
# ---------------------------------------------------------------------------
TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parent
GENERATE_SCRIPT = TOOL_DIR / "generate_proxy_nodes.py"
LOCAL_INI = (
    REPO_ROOT / "Clash" / "config" / "ACL4SSR_Online_Full_self.ini"
)

DEFAULT_ROUTER_HOST = "istore"
DEFAULT_ROUTER_IP = "192.168.0.1"
DEFAULT_SS_REMOTE = "/www/luci-static/resources/ss.json"
DEFAULT_INI_REMOTE = "/www/luci-static/resources/ACL4SSR_Online_Full_self.ini"
DEFAULT_CLASH_CONFIG_NAME = "self-github-ssr-V1.yaml"
DEFAULT_CLASH_CONFIG_REMOTE = f"/etc/openclash/config/{DEFAULT_CLASH_CONFIG_NAME}"
DEFAULT_SUB_PORT = 25500
# GitHub 上的规则（当 --use-github-ini 时使用；本地 ini 优先时用路由器上的副本）
DEFAULT_GITHUB_INI = (
    "https://raw.githubusercontent.com/blackj-x/ACL4SSR/master/"
    "Clash/config/ACL4SSR_Online_Full_self.ini"
)

LOCAL_OUT_YAML = TOOL_DIR / "openclash_self-github-ssr-V1.yaml"
LOCAL_B64 = TOOL_DIR / "ss_uris.txt.b64"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class StepError(RuntimeError):
    pass


def log(msg: str = "") -> None:
    print(msg, flush=True)


def log_step(n: int, total: int, title: str) -> None:
    log(f"\n[{n}/{total}] {title}")
    log("-" * 60)


def run(
    cmd: list[str] | str,
    *,
    check: bool = True,
    capture: bool = False,
    timeout: int | None = None,
    shell: bool = False,
) -> subprocess.CompletedProcess:
    log(f"  $ {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture,
            text=True,
            timeout=timeout,
            shell=shell,
        )
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or "").strip()
        raise StepError(f"命令失败 ({e.returncode}): {err or cmd}") from e
    except subprocess.TimeoutExpired as e:
        raise StepError(f"命令超时: {cmd}") from e


def ssh(host: str, remote_cmd: str, *, timeout: int = 120, check: bool = True) -> str:
    cp = run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            host,
            remote_cmd,
        ],
        check=check,
        capture=True,
        timeout=timeout,
    )
    return (cp.stdout or "") + (cp.stderr or "")


def scp_to(host: str, local: Path, remote: str, *, timeout: int = 120) -> None:
    if not local.is_file():
        raise StepError(f"本地文件不存在: {local}")
    run(
        [
            "scp",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            str(local),
            f"{host}:{remote}",
        ],
        timeout=timeout,
    )


def build_subconverter_url(
    *,
    router_ip: str,
    sub_port: int,
    ss_http_url: str,
    config_url: str,
) -> str:
    """构造与 OpenClash 订阅相同的 subconverter URL。"""
    q = {
        "target": "clash",
        "url": ss_http_url,
        "insert": "false",
        "config": config_url,
        "emoji": "true",
        "list": "false",
        "tfo": "false",
        "scv": "true",
        "fdn": "false",
        "sort": "false",
        "new_name": "true",
    }
    # 与面板里一致：带 cache-buster 的 config 参数可用外部传入
    return f"http://{router_ip}:{sub_port}/sub?{urllib.parse.urlencode(q)}"


def http_get(url: str, *, timeout: int = 180) -> bytes:
    log(f"  GET {url[:140]}{'...' if len(url) > 140 else ''}")
    req = urllib.request.Request(url, headers={"User-Agent": "update_openclash/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            code = getattr(resp, "status", 200)
            if code != 200:
                raise StepError(f"HTTP {code} from subconverter")
            return data
    except urllib.error.URLError as e:
        raise StepError(f"请求 subconverter 失败: {e}") from e


def extract_proxy_names(yaml_text: str) -> list[str]:
    """从 proxies: 段提取 name（inline map 或 block）。"""
    m = re.search(r"(?m)^proxies:\s*\n", yaml_text)
    if not m:
        return []
    start = m.end()
    m2 = re.search(r"(?m)^proxy-groups:\s*$", yaml_text[start:])
    section = yaml_text[start : start + m2.start()] if m2 else yaml_text[start:]
    names: list[str] = []
    # - {name: xxx, ...}  or  - {name: "xxx", ...}
    for m in re.finditer(
        r"name:\s*(?:\"([^\"]+)\"|'([^']+)'|([^,}]+))", section
    ):
        name = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if name:
            names.append(name)
    return names


def fix_broken_bracket_lists(yaml_text: str) -> tuple[str, int]:
    """
    修复 subconverter / 手残产生的非法列表项：
      - 🇯🇵 日本节点[]🇭🇰 香港节点[]🇸🇬 狮城节点
    拆成多行。
    返回 (new_text, fix_count)。
    """
    fixed = 0

    def repl(match: re.Match) -> str:
        nonlocal fixed
        indent, body = match.group(1), match.group(2)
        if "[]" not in body:
            return match.group(0)
        parts = [p.strip() for p in body.split("[]") if p.strip()]
        if len(parts) <= 1:
            return match.group(0)
        fixed += 1
        return "\n".join(f"{indent}- {p}" for p in parts)

    # 只处理看起来像「被 [] 粘在一起」的列表项
    new = re.sub(
        r"^([ \t]*)- (.+\[].+)$",
        repl,
        yaml_text,
        flags=re.MULTILINE,
    )
    return new, fixed


# 不参与 ♻️ 自动选择 的节点（家宽等）；仍保留在「手动切换」里
AUTO_SELECT_EXCLUDE = re.compile(r"G-Home|GHome|家宽|回家", re.I)
# 与 ACL4SSR_Online_Full_self.ini 中自动选择正则一致
AUTO_SELECT_INCLUDE = re.compile(r"(CN\d+|SG\d+|US\d+|TR\d+)", re.I)


def filter_auto_select_names(proxy_names: list[str]) -> list[str]:
    """自动选择：只要业务节点，排除 G-Home 等。"""
    out: list[str] = []
    for n in proxy_names:
        if AUTO_SELECT_EXCLUDE.search(n):
            continue
        if AUTO_SELECT_INCLUDE.search(n):
            out.append(n)
    return out


def ensure_auto_select_has_nodes(yaml_text: str, proxy_names: list[str]) -> tuple[str, bool]:
    """
    校正 ♻️ 自动选择（按行解析，避免 DOTALL 把整份 YAML 吃掉）：
      - 去掉 G-Home
      - 若列表为空 / 只有 DIRECT / 含非法 [] 粘连，则用合格 leaf 节点重写
    """
    wanted = filter_auto_select_names(proxy_names)
    if not wanted:
        return yaml_text, False

    lines = yaml_text.splitlines(keepends=True)
    # 找 group 定义行：  - name: ♻️ 自动选择
    group_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^[ \t]*- name:\s*♻️ 自动选择\s*$", ln):
            group_idx = i
            break
    if group_idx is None:
        return yaml_text, False

    # 在该 group 内找 proxies:
    proxies_idx = None
    for j in range(group_idx + 1, len(lines)):
        # 下一个同级 group 开始则失败
        if re.match(r"^[ \t]*- name:\s*", lines[j]) and j > group_idx:
            break
        if re.match(r"^[ \t]*proxies:\s*$", lines[j]):
            proxies_idx = j
            break
    if proxies_idx is None:
        return yaml_text, False

    # 收集 proxies 列表项（仅更深缩进的 - xxx）
    list_start = proxies_idx + 1
    list_end = list_start
    base_indent = len(lines[proxies_idx]) - len(lines[proxies_idx].lstrip(" \t"))
    current: list[str] = []
    while list_end < len(lines):
        ln = lines[list_end]
        if not ln.strip():
            list_end += 1
            continue
        indent = len(ln) - len(ln.lstrip(" \t"))
        stripped = ln.lstrip(" \t")
        if indent > base_indent and stripped.startswith("- "):
            current.append(stripped[2:].strip())
            list_end += 1
            continue
        break

    body_has_bad = any("[]" in c for c in current)
    needs = (
        body_has_bad
        or not current
        or all(c in {"DIRECT", "REJECT"} for c in current)
        or any(AUTO_SELECT_EXCLUDE.search(c) for c in current)
        or (len(current) == 1 and current[0].count("节点") >= 2)
        or set(current) != set(wanted)
    )
    if not needs:
        return yaml_text, False

    # 用与原列表项相同的缩进
    item_indent = "      "
    if list_start < list_end:
        sample = lines[list_start]
        item_indent = sample[: len(sample) - len(sample.lstrip(" \t"))]
    new_block = [f"{item_indent}- {n}\n" for n in wanted]
    new_lines = lines[:list_start] + new_block + lines[list_end:]
    return "".join(new_lines), True


def _rule_dedupe_key(rule_body: str) -> str | None:
    """
    规则去重键 = 类型 + 匹配载荷（不含策略组 / no-resolve）。
    与 Clash 先匹配先生效一致：同键只保留第一次出现。
    例: DOMAIN-SUFFIX,claude.ai,🇺🇲 US直连  →  DOMAIN-SUFFIX|claude.ai
        DOMAIN-KEYWORD,claude,🌍 国外媒体   →  DOMAIN-KEYWORD|claude
        IP-CIDR,1.2.3.0/24,DIRECT,no-resolve → IP-CIDR|1.2.3.0/24
    """
    body = rule_body.strip().strip("'\"")
    if not body:
        return None
    # 特殊规则：整条保留语义
    upper = body.upper()
    if upper in {"MATCH", "FINAL"} or upper.startswith("GEOIP,") or upper.startswith("MATCH,"):
        # GEOIP,CN,直连 与 GEOIP,CN,其他 视为同键（按国家码）
        parts = [p.strip() for p in body.split(",")]
        if parts[0].upper() == "GEOIP" and len(parts) >= 2:
            return f"GEOIP|{parts[1].upper()}"
        if parts[0].upper() in {"MATCH", "FINAL"}:
            return parts[0].upper()
        return upper

    parts = [p.strip() for p in body.split(",")]
    if len(parts) < 2:
        return body.lower()

    rtype = parts[0].upper()
    payload = parts[1]
    # 域名类统一小写，避免大小写重复
    if rtype in {
        "DOMAIN",
        "DOMAIN-SUFFIX",
        "DOMAIN-KEYWORD",
        "DOMAIN-REGEX",
        "PROCESS-NAME",
        "PROCESS-PATH",
    }:
        payload = payload.lower()
    return f"{rtype}|{payload}"


def dedupe_clash_rules(yaml_text: str) -> tuple[str, dict]:
    """
    按 ini/生成顺序去重 rules：同一「类型+匹配值」只保留首次（即实际会生效的那条）。
    返回 (new_yaml, stats)。
    """
    lines = yaml_text.splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^rules:\s*$", ln):
            start = i
            break
    if start is None:
        return yaml_text, {"kept": 0, "removed": 0, "total": 0}

    # rules 段一直到文件末尾，或下一个顶层 key（少见）
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*:\s*", lines[j]):
            end = j
            break

    seen: set[str] = set()
    kept_lines: list[str] = []
    removed = 0
    total_rules = 0
    # 保留 rules: 标题
    out_head = lines[: start + 1]
    for ln in lines[start + 1 : end]:
        raw = ln.strip()
        if not raw or raw.startswith("#"):
            kept_lines.append(ln)
            continue
        if not raw.startswith("- "):
            kept_lines.append(ln)
            continue
        total_rules += 1
        body = raw[2:].strip()
        key = _rule_dedupe_key(body)
        if key is None:
            kept_lines.append(ln)
            continue
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        kept_lines.append(ln)

    new_text = "".join(out_head + kept_lines + lines[end:])
    return new_text, {
        "kept": total_rules - removed,
        "removed": removed,
        "total": total_rules,
    }


def validate_clash_yaml(yaml_text: str) -> list[str]:
    """轻量校验，返回问题列表（空 = OK）。"""
    problems: list[str] = []
    if len(yaml_text) < 500:
        problems.append(f"配置过短 ({len(yaml_text)} bytes)，可能不是有效 Clash YAML")
    if "proxies:" not in yaml_text:
        problems.append("缺少 proxies: 段")
    if "proxy-groups:" not in yaml_text:
        problems.append("缺少 proxy-groups: 段")
    if "rules:" not in yaml_text:
        problems.append("缺少 rules: 段（规则可能未生成）")
    # 致命的 [] 粘连
    bad = re.findall(r"(?m)^[ \t]*- .+\[].+$", yaml_text)
    if bad:
        problems.append(f"仍存在非法节点列表项 ({len(bad)} 处): {bad[0][:80]}")
    names = extract_proxy_names(yaml_text)
    if len(names) < 1:
        problems.append("proxies 段未解析到任何节点")
    return problems


def generate_nodes(service_ids: list[int] | None) -> None:
    """调用 generate_proxy_nodes.py 写本地 b64；scp 由本脚本统一做。"""
    cmd = [sys.executable, str(GENERATE_SCRIPT)]
    if service_ids:
        for sid in service_ids:
            cmd.extend(["--service", str(sid)])
    log("  运行 generate_proxy_nodes.py …")
    cp = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if cp.returncode != 0:
        log(cp.stderr or cp.stdout)
        raise StepError("generate_proxy_nodes.py 失败")
    for line in (cp.stderr or "").splitlines():
        if line.strip():
            log(f"  {line}")
    if not LOCAL_B64.is_file():
        raise StepError(f"未生成 {LOCAL_B64}")
    log(f"  已生成节点 base64: {LOCAL_B64} ({LOCAL_B64.stat().st_size} bytes)")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="一键更新软路由 OpenClash（节点 + ACL4SSR 规则 + 重启）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--router-host",
        default=DEFAULT_ROUTER_HOST,
        help=f"SSH 别名/主机 (default: {DEFAULT_ROUTER_HOST})",
    )
    parser.add_argument(
        "--router-ip",
        default=DEFAULT_ROUTER_IP,
        help=f"路由器 LAN IP，用于 subconverter URL (default: {DEFAULT_ROUTER_IP})",
    )
    parser.add_argument(
        "--sub-port",
        type=int,
        default=DEFAULT_SUB_PORT,
        help=f"subconverter 端口 (default: {DEFAULT_SUB_PORT})",
    )
    parser.add_argument(
        "--ss-remote",
        default=DEFAULT_SS_REMOTE,
        help=f"ss.json 远程路径 (default: {DEFAULT_SS_REMOTE})",
    )
    parser.add_argument(
        "--clash-remote",
        default=DEFAULT_CLASH_CONFIG_REMOTE,
        help=f"OpenClash 配置远程路径 (default: {DEFAULT_CLASH_CONFIG_REMOTE})",
    )
    parser.add_argument(
        "--service",
        action="append",
        type=int,
        dest="service_ids",
        metavar="ID",
        help="只导出该 MonoProxy service id（可重复）",
    )
    parser.add_argument(
        "--skip-generate",
        action="store_true",
        help="跳过 MonoProxy 生成，使用现有 Tool/ss_uris.txt.b64",
    )
    parser.add_argument(
        "--nodes-only",
        action="store_true",
        help="只生成并推送 ss.json，不转换/不写 OpenClash yaml",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="写完配置后不重启 OpenClash",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="转换结果只写本地 Tool/openclash_*.yaml，不 scp、不重启",
    )
    parser.add_argument(
        "--use-github-ini",
        action="store_true",
        help="规则 ini 使用 GitHub raw（默认：上传本地 ini 到路由器再引用，避免未 push 的修复失效）",
    )
    parser.add_argument(
        "--github-ini",
        default=DEFAULT_GITHUB_INI,
        help="--use-github-ini 时的 ini URL",
    )
    parser.add_argument(
        "--sub-timeout",
        type=int,
        default=180,
        help="subconverter 请求超时秒数 (default: 180)",
    )
    parser.add_argument(
        "--wait-after-restart",
        type=int,
        default=25,
        help="重启后等待多少秒再检查 (default: 25)",
    )
    parser.add_argument(
        "--no-dedupe-rules",
        action="store_true",
        help="不去重 rules（默认会按「类型+匹配值」保留首次命中，去掉后面的死规则）",
    )
    parser.add_argument(
        "--dedupe-file",
        metavar="YAML",
        help="只对本地某个 Clash YAML 做规则去重并写回（可另存为 --dedupe-out）",
    )
    parser.add_argument(
        "--dedupe-out",
        metavar="YAML",
        help="配合 --dedupe-file：去重结果输出路径（默认覆盖原文件）",
    )
    args = parser.parse_args()

    # 独立模式：只去重某个 yaml（给 ClashX / 本地配置用）
    if args.dedupe_file:
        src = Path(args.dedupe_file).expanduser()
        if not src.is_file():
            raise SystemExit(f"ERROR: 文件不存在: {src}")
        text = src.read_text(encoding="utf-8")
        new_text, st = dedupe_clash_rules(text)
        out = Path(args.dedupe_out).expanduser() if args.dedupe_out else src
        out.write_text(new_text, encoding="utf-8")
        log(
            f"✓ 规则去重完成: 原 {st['total']} → 保留 {st['kept']}，删除重复 {st['removed']}\n"
            f"  输出: {out} ({out.stat().st_size} bytes)"
        )
        return 0

    host = args.router_host
    dry = args.dry_run
    total_steps = 6
    if args.nodes_only:
        total_steps = 3
    step = 0

    log("=" * 60)
    log("OpenClash 一键更新")
    log(f"  时间        : {datetime.now().isoformat(timespec='seconds')}")
    log(f"  SSH         : {host}")
    log(f"  LAN IP      : {args.router_ip}")
    log(f"  dry-run     : {dry}")
    log(f"  skip-generate: {args.skip_generate}")
    log(f"  nodes-only  : {args.nodes_only}")
    log("=" * 60)

    # 0) SSH 连通性
    step += 1
    log_step(step, total_steps, "检查 SSH 连通性")
    if not dry:
        out = ssh(host, "uname -n && echo OK", timeout=15)
        log(f"  {out.strip()}")
    else:
        log("  (dry-run 跳过实时 SSH 检查，后续 scp 也会跳过)")

    # 1) 生成节点
    step += 1
    log_step(step, total_steps, "从 MonoProxy 生成节点 (ss_uris.txt.b64)")
    if args.skip_generate:
        if not LOCAL_B64.is_file():
            raise SystemExit(f"ERROR: --skip-generate 但找不到 {LOCAL_B64}")
        log(f"  使用现有文件: {LOCAL_B64} ({LOCAL_B64.stat().st_size} bytes)")
    else:
        generate_nodes(args.service_ids)

    # 2) 推送 ss.json
    step += 1
    log_step(step, total_steps, f"推送 ss.json → {host}:{args.ss_remote}")
    if dry:
        log("  dry-run: 跳过 scp ss.json")
    else:
        # 备份
        ssh(
            host,
            f"cp '{args.ss_remote}' '{args.ss_remote}.bak-$(date +%Y%m%d-%H%M%S)' 2>/dev/null || true",
            timeout=20,
            check=False,
        )
        scp_to(host, LOCAL_B64, args.ss_remote)
        # 校验
        remote_size = ssh(host, f"wc -c < '{args.ss_remote}'", timeout=15).strip()
        log(f"  远程 ss.json 大小: {remote_size} bytes")

    if args.nodes_only:
        log("\n✓ --nodes-only：已完成节点推送。OpenClash 需另跑完整更新或等订阅刷新。")
        return 0

    # 3) 准备规则 ini + 调 subconverter
    step += 1
    log_step(step, total_steps, "调用 subconverter 生成 Clash 配置")

    if args.use_github_ini:
        config_url = args.github_ini
        # cache bust
        sep = "&" if "?" in config_url else "?"
        config_url = f"{config_url}{sep}t={int(time.time())}"
        log(f"  规则 ini: GitHub → {config_url}")
    else:
        if not LOCAL_INI.is_file():
            raise SystemExit(f"ERROR: 本地 ini 不存在: {LOCAL_INI}")
        if dry:
            log(f"  dry-run: 将使用 GitHub ini（本地无法让路由器读你的磁盘）")
            config_url = f"{args.github_ini}?t={int(time.time())}"
        else:
            log(f"  上传本地 ini → {host}:{DEFAULT_INI_REMOTE}")
            scp_to(host, LOCAL_INI, DEFAULT_INI_REMOTE)
            config_url = f"http://{args.router_ip}/luci-static/resources/ACL4SSR_Online_Full_self.ini"
            log(f"  规则 ini: {config_url}")

    ss_http = f"http://{args.router_ip}/luci-static/resources/ss.json"
    # dry-run 且未推送时，ss.json 仍是路由器上旧的——提示用户
    if dry and not args.skip_generate:
        log("  注意: dry-run 未推送新 ss.json，转换结果可能仍用路由器上旧节点")

    sub_url = build_subconverter_url(
        router_ip=args.router_ip,
        sub_port=args.sub_port,
        ss_http_url=ss_http,
        config_url=config_url,
    )
    # 先探活
    try:
        ver = http_get(
            f"http://{args.router_ip}:{args.sub_port}/version", timeout=10
        ).decode("utf-8", "replace")
        log(f"  subconverter: {ver.strip()}")
    except StepError as e:
        raise SystemExit(
            f"ERROR: 连不上 subconverter ({args.router_ip}:{args.sub_port}): {e}\n"
            "  请确认软路由上 subconverter / docker 在跑。"
        ) from e

    raw = http_get(sub_url, timeout=args.sub_timeout)
    try:
        yaml_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        yaml_text = raw.decode("utf-8", "replace")
    log(f"  原始配置大小: {len(yaml_text)} bytes / {yaml_text.count(chr(10))+1} lines")

    # 4) 修复 + 校验
    step += 1
    log_step(step, total_steps, "修复已知坏格式并校验")
    yaml_text, n_fix = fix_broken_bracket_lists(yaml_text)
    if n_fix:
        log(f"  已拆分 {n_fix} 处非法 '[]' 粘连列表项")
    names = extract_proxy_names(yaml_text)
    log(f"  节点数: {len(names)}")
    if names:
        preview = ", ".join(names[:8])
        more = f" …(+{len(names)-8})" if len(names) > 8 else ""
        log(f"  节点: {preview}{more}")
    yaml_text, auto_fixed = ensure_auto_select_has_nodes(yaml_text, names)
    if auto_fixed:
        auto_n = len(filter_auto_select_names(names))
        log(f"  已校正 ♻️ 自动选择 → {auto_n} 个节点（已排除 G-Home）")

    if not args.no_dedupe_rules:
        yaml_text, st = dedupe_clash_rules(yaml_text)
        log(
            f"  规则去重: {st['total']} → {st['kept']} "
            f"(删除重复/死规则 {st['removed']})"
        )
    else:
        log("  跳过规则去重 (--no-dedupe-rules)")

    problems = validate_clash_yaml(yaml_text)
    if problems:
        for p in problems:
            log(f"  ✗ {p}")
        LOCAL_OUT_YAML.write_text(yaml_text, encoding="utf-8")
        log(f"  有问题的配置已保存到 {LOCAL_OUT_YAML} 供排查")
        raise SystemExit("ERROR: 配置校验失败，已中止（未覆盖路由器配置）")
    log("  校验通过")

    LOCAL_OUT_YAML.write_text(yaml_text, encoding="utf-8")
    log(f"  本地副本: {LOCAL_OUT_YAML} ({LOCAL_OUT_YAML.stat().st_size} bytes)")

    if dry:
        log("\n✓ dry-run 完成。配置仅写在本地，路由器未改动。")
        log(f"  查看: {LOCAL_OUT_YAML}")
        return 0

    # 5) 推送 yaml + 重启
    step += 1
    log_step(step, total_steps, f"推送配置并重启 OpenClash → {args.clash_remote}")
    # 备份远程
    ssh(
        host,
        f"cp '{args.clash_remote}' '{args.clash_remote}.bak-$(date +%Y%m%d-%H%M%S)' 2>/dev/null || true",
        timeout=30,
        check=False,
    )
    scp_to(host, LOCAL_OUT_YAML, args.clash_remote, timeout=180)
    remote_sz = ssh(host, f"wc -c < '{args.clash_remote}'", timeout=15).strip()
    log(f"  远程 yaml 大小: {remote_sz} bytes")

    # 在路由器上用 clash -t 测一下（用一份临时目录，避免动运行时）
    log("  远程 clash -t 语法测试 …")
    test_out = ssh(
        host,
        "WORKDIR=/tmp/clash-cfg-test; rm -rf $WORKDIR; mkdir -p $WORKDIR; "
        "cp /etc/openclash/Country.mmdb $WORKDIR/ 2>/dev/null; "
        f"cp '{args.clash_remote}' $WORKDIR/config.yaml; "
        "/etc/openclash/core/clash -t -d $WORKDIR -f $WORKDIR/config.yaml 2>&1 | tail -20; "
        "echo EXIT:$?",
        timeout=60,
        check=False,
    )
    log("  " + "\n  ".join(test_out.strip().splitlines()[-15:]))
    if "EXIT:0" not in test_out and "test is successful" not in test_out.lower():
        # clash -t 成功时通常 exit 0；部分版本只打印 successful
        if re.search(r"level=fatal|Parse config error", test_out):
            raise SystemExit(
                "ERROR: 远程 clash -t 失败，未重启。请检查配置。\n" + test_out
            )

    if args.no_restart:
        log("  --no-restart：跳过重启。请在合适时手动: /etc/init.d/openclash restart")
        return 0

    log("  重启 OpenClash（可能需要 1–2 分钟）…")
    # enable + restart
    ssh(
        host,
        "uci set openclash.config.enable=1; uci commit openclash; "
        "/etc/init.d/openclash restart",
        timeout=300,
        check=False,
    )
    wait = max(10, args.wait_after_restart)
    log(f"  等待 {wait}s 后检查进程 …")
    time.sleep(wait)

    status = ssh(
        host,
        "ps w | grep -E '[/]etc/openclash/clash |[/]openclash_watchdog' | grep -v grep; "
        "echo '---LOG_TAIL---'; "
        "tail -30 /tmp/openclash.log 2>/dev/null",
        timeout=30,
        check=False,
    )
    log(status)

    # 只根据「进程是否在跑 + 日志末尾是否成功」判断，忽略更早的历史 fatal
    ok_proc = bool(re.search(r"/etc/openclash/clash\s", status))
    log_tail = status.split("---LOG_TAIL---", 1)[-1] if "---LOG_TAIL---" in status else status
    recent_lines = log_tail.strip().splitlines()[-25:]
    recent_text = "\n".join(recent_lines)
    ok_start = bool(
        re.search(r"OpenClash Start Successful|Start Successful", recent_text)
    )
    recent_fatal = bool(
        re.search(r"level=fatal|Parse config error", recent_text)
    )

    if ok_proc and ok_start and not recent_fatal:
        log("\n" + "=" * 60)
        log("✓ 完成：节点已更新，Clash 配置已写入，OpenClash 正在运行。")
        log(f"  配置: {args.clash_remote}")
        log(f"  本地: {LOCAL_OUT_YAML}")
        log("=" * 60)
        return 0

    if ok_proc and not recent_fatal:
        log("\n" + "=" * 60)
        log("✓ Clash 进程在跑（日志里未必刚刷出 Successful，但无新 fatal）。")
        log(f"  配置: {args.clash_remote}")
        log("=" * 60)
        return 0

    if recent_fatal:
        log("\n✗ 最近日志仍有 fatal / Parse config error，请检查。")
        return 2

    log(
        "\n? 未在进程列表中看到 clash（可能还在启动）。"
        "稍后执行: ssh %s \"tail -30 /tmp/openclash.log\"" % host
    )
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StepError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        raise SystemExit(130)
