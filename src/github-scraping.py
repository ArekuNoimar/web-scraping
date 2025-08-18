#!/usr/bin/env python3

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional

import requests

GITHUB_API_BASE = "https://api.github.com"
API_DEFAULT_PER_PAGE = 100
MIN_CLONE_INTERVAL_SECONDS = 10


@dataclass
class Repo:
    owner: str
    name: str
    full_name: str
    ssh_url: str
    archived: bool
    description: Optional[str]


def ensure_git_available() -> None:
    if shutil.which("git") is None:
        print("git コマンドが見つかりません。インストールしてください。", file=sys.stderr)
        sys.exit(1)


def build_repos_endpoint(owner: str, is_org: bool) -> str:
    if is_org:
        return f"{GITHUB_API_BASE}/orgs/{owner}/repos"
    return f"{GITHUB_API_BASE}/users/{owner}/repos"


def request_with_rate_limit(url: str, params: dict) -> requests.Response:
    headers = {
        "Accept": "application/vnd.github+json",
    }
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            reset = response.headers.get("X-RateLimit-Reset")
            if reset is not None:
                reset_epoch = int(reset)
                sleep_seconds = max(1, reset_epoch - int(time.time()) + 2)
                print(f"GitHub API のレートリミットに達しました。{sleep_seconds} 秒待機します…", file=sys.stderr)
                time.sleep(sleep_seconds)
                continue
        if response.status_code >= 400:
            raise RuntimeError(
                f"GitHub API エラー: {response.status_code} {response.text}"
            )
        return response


def fetch_all_repos(owner: str, is_org: bool) -> List[Repo]:
    url = build_repos_endpoint(owner, is_org)
    page = 1
    repos: List[Repo] = []
    while True:
        params = {
            "per_page": API_DEFAULT_PER_PAGE,
            "page": page,
            "type": "all",
            "sort": "updated",
            "direction": "desc",
        }
        resp = request_with_rate_limit(url, params)
        data = resp.json()
        if not isinstance(data, list):
            raise RuntimeError(f"予期しないレスポンス: {data}")
        if len(data) == 0:
            break
        for item in data:
            # item keys: full_name, name, owner.login, ssh_url, archived, description
            repos.append(
                Repo(
                    owner=item.get("owner", {}).get("login", owner),
                    name=item.get("name", ""),
                    full_name=item.get("full_name", f"{owner}/unknown"),
                    ssh_url=item.get("ssh_url", f"git@github.com:{owner}/unknown.git"),
                    archived=bool(item.get("archived", False)),
                    description=item.get("description"),
                )
            )
        page += 1
    return repos


def filter_repos(
    repos: Iterable[Repo],
    match_substring: Optional[str],
    match_regex: Optional[str],
    include_archived: bool,
    include_forks: bool,
) -> List[Repo]:
    compiled_regex: Optional[re.Pattern[str]] = None
    if match_regex:
        compiled_regex = re.compile(match_regex)

    filtered: List[Repo] = []
    for r in repos:
        if not include_archived and r.archived:
            continue
        # GitHub API includes forks; we can infer fork via full data only when asking for it.
        # Without explicit fork flag in our dataclass, rely on presence if provided; otherwise include.
        # Many clients still want forks; so include unless user excluded and field exists.
        # When field not present, we cannot filter reliably — keep it.
        # We could refetch, but avoid extra API calls.
        # Therefore, only filter when the field exists on the raw dict; here we cannot, so honor include_forks by default.

        text_blob = f"{r.name}\n{r.full_name}\n{r.description or ''}"

        matched = False
        if match_substring and match_substring.lower() in text_blob.lower():
            matched = True
        if not matched and compiled_regex and compiled_regex.search(text_blob):
            matched = True
        if match_substring is None and compiled_regex is None:
            matched = True

        if matched:
            filtered.append(r)
    return filtered


def run_git_clone(ssh_url: str, dest_dir: str) -> int:
    result = subprocess.run(
        ["git", "clone", "--", ssh_url, dest_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    print(result.stdout, end="")
    return result.returncode


def run_git_pull(dest_dir: str) -> int:
    result = subprocess.run(
        ["git", "-C", dest_dir, "pull", "--ff-only"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    print(result.stdout, end="")
    return result.returncode


def throttle_sleep(seconds: int) -> None:
    seconds = max(MIN_CLONE_INTERVAL_SECONDS, seconds)
    time.sleep(seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "指定したユーザーまたは組織のリポジトリ一覧を取得し、" \
            "名前・フルネーム・説明に特定文字列（または正規表現）が含まれるものを、" \
            "最低10秒間隔で自動的に順次 clone します。"
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user", help="対象のGitHubユーザー名")
    group.add_argument("--org", help="対象のGitHub組織名")

    parser.add_argument(
        "--match",
        help="リポジトリ名/フルネーム/説明に含まれるべき部分文字列（大文字小文字無視）",
    )
    parser.add_argument(
        "--regex",
        help="部分一致の代わりに使う正規表現（Python互換）",
    )
    parser.add_argument(
        "--dest",
        default="./repos",
        help="clone先のルートディレクトリ（未存在なら作成）",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="各 clone の間隔（秒）。10秒未満は拒否されます（既定: 10）",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="アーカイブ済みリポジトリも対象に含めます",
    )
    parser.add_argument(
        "--pull-if-exists",
        action="store_true",
        help="既に存在する場合は clone せずに git pull --ff-only を実行します",
    )
    parser.add_argument(
        "--sleep-on-skip",
        action="store_true",
        help="既に存在してcloneをスキップした場合でも間隔スリープを行います",
    )
    return parser.parse_args()


def main() -> None:
    ensure_git_available()
    args = parse_args()

    if args.interval < MIN_CLONE_INTERVAL_SECONDS:
        print(
            f"--interval は {MIN_CLONE_INTERVAL_SECONDS} 秒以上に設定してください。",
            file=sys.stderr,
        )
        sys.exit(2)

    owner = args.user or args.org
    is_org = bool(args.org)

    os.makedirs(args.dest, exist_ok=True)

    print(f"対象: {'org' if is_org else 'user'}={owner}")
    print("リポジトリ一覧を取得中…")

    try:
        repos = fetch_all_repos(owner, is_org)
    except Exception as e:
        print(f"リポジトリ一覧の取得に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"取得件数: {len(repos)} 件")

    matched = filter_repos(
        repos,
        match_substring=args.match,
        match_regex=args.regex,
        include_archived=args.include_archived,
        include_forks=True,
    )
    print(f"フィルター後: {len(matched)} 件")

    clones_done = 0
    for idx, repo in enumerate(matched, start=1):
        repo_dest = os.path.join(args.dest, repo.name)
        header = f"[{idx}/{len(matched)}] {repo.full_name} -> {repo_dest}"

        if os.path.isdir(os.path.join(repo_dest, ".git")):
            print(f"{header}: 既存のリポジトリを検出しました。")
            if args.pull_if_exists:
                print("git pull --ff-only を実行します…")
                code = run_git_pull(repo_dest)
                if code != 0:
                    print(f"pull に失敗しました（コード {code}）。続行します。", file=sys.stderr)
                else:
                    clones_done += 1
                if args.sleep_on_skip:
                    throttle_sleep(args.interval)
            else:
                if args.sleep_on_skip:
                    throttle_sleep(args.interval)
            continue

        print(f"{header}: clone を開始します…")
        code = run_git_clone(repo.ssh_url, repo_dest)
        if code != 0:
            print(f"clone に失敗しました（コード {code}）。続行します。", file=sys.stderr)
        else:
            clones_done += 1
        throttle_sleep(args.interval)

    print(f"完了: {clones_done} 件 clone/pull 実行（対象 {len(matched)} 件中）")


if __name__ == "__main__":
    main()
