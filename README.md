# codesearch-mcp

```text
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│    $ rg /pattern/  ─►  📡 MCP  ─►  🤖  "src/foo.py:142 から…"       │
│                                                                     │
│            git  ×  ripgrep  ×  Model Context Protocol               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

> **エージェントに「人間が grep でコードを追う手順」をそのまま渡す MCP サーバー。**
>
> ベクトル検索なし。埋め込みインデックスなし。
> 引用は Git URL (行アンカー付き) で即貼り付け。

[![verify](https://github.com/nncdevel-io/codesearch-mcp-python/actions/workflows/verify.yml/badge.svg)](https://github.com/nncdevel-io/codesearch-mcp-python/actions/workflows/verify.yml)
[![version](https://img.shields.io/badge/dynamic/toml?url=https%3A%2F%2Fraw.githubusercontent.com%2Fnncdevel-io%2Fcodesearch-mcp-python%2Fmain%2Fpyproject.toml&query=%24.project.version&label=version&color=blue&prefix=v)](pyproject.toml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](#-ライセンス)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![MCP](https://img.shields.io/badge/MCP-compatible-blueviolet.svg)](https://spec.modelcontextprotocol.io/)

---

## 🚀 これは何？

Git 管理されたソースコードを **チャット AI から直接 grep する** ための
Model Context Protocol (MCP) サーバー。Claude Code・Claude Desktop・自前の
エージェントから、人間が `rg` と `git ls-files` でコードを追う手順を、
**そのままツール呼び出し** として実行させる。

- 🧠 **埋め込み・ベクトル DB なし** — `ripgrep` と `git ls-files` だけで
  十分に速く、正確で、引用可能 (要件書 §1.3 / §6.2)
- 🔗 **結果は Git URL でそのまま貼れる** — 行アンカー付きで GitHub /
  GitLab / Bitbucket / Gitea を生成
- 🛡️ **per-repo 分離** — 1 つのリポジトリの failure は他へ波及しない
- ⏱️ **request path に blocking git pull なし** — 同期は CLI / スケジューラ
  経由で完全に分離 (p95 2s / 可用性要件を守る)
- 🔌 **stdio と Streamable HTTP の両方** — どちらでも同じツールが使える

---

## 🧰 公開ツール (5) + Resource

| 🔧 ツール | 何ができる | 主な入力 | 主な出力 |
| --- | --- | --- | --- |
| 🔍 `search_code` | ファイル内容の正規表現検索 | `pattern`, `repository`, `glob`/`type`, `output_mode` | ヒット行 + Git URL (行アンカー) |
| 📄 `list_files` | グロブによるファイル名検索 | `pattern`, `repository` | パス + 最終更新時刻 + Git URL |
| 🌳 `list_tree` | ディレクトリ階層の俯瞰 | `repository`, `max_depth`, `max_entries` | ASCII ツリー |
| 📖 `read_file` | 行範囲指定でファイル内容を読む | `repository`, `file_path`, `start_line`, `num_lines` | 行番号付き内容 + Git URL |
| 🗂️ `list_repositories` | 設定済みリポジトリのカタログ (LLM 向け discovery) | — | id / branch / hosting / status の配列 |

加えて、設定済みリポジトリは MCP の **Resource** としても
`codesearch://repo/{id}` に広告される (Resources 対応ホストでは
`resources/list` で同じカタログを取得できる)。

📘 完全な入出力スキーマとエラーコード一覧は
[`docs/spec/spec.md`](docs/spec/spec.md) を参照。

---

## 🏁 3 ステップで使い始める

**1️⃣ インストール** — `uv sync --frozen` で依存を入れ、`config/repos.toml`
(検索対象、必須) と必要なら `config/secrets.toml` (認証情報)、起動
パラメータをファイルで持ちたい場合は `config/server.toml` を置く。
これらは **同梱の `.example` をコピーしてリポ直下の `config/` に置けば
auto-discovery で読まれる** (CLI / env で上書き可)。
👉 詳細: [`docs/installation.md`](docs/installation.md)

**2️⃣ サーバーを HTTP で起動する** — `uv run codesearch-mcp serve
--transport http` を常駐させ、MCP クライアントから
`http://<host>:<port>/mcp/` を指す。個人開発で **stdio** でクライアント
直結したい場合は
[`docs/installation.md`](docs/installation.md#開発者向け-stdio-でローカル起動する)
を参照。

**3️⃣ (任意) 定期同期を構成** — 常設で動かす場合は cron / systemd / 同居
スケジューラのいずれかを選ぶ。外部 `codesearch-sync` は完了時に
`SIGHUP` で実行中の serve を通知するので **再起動なしで** 状態反映される。
👉 詳細: [`docs/operations.md`](docs/operations.md)

---

## 🌐 サーバー起動 (Streamable HTTP)

本サーバは **チーム / 複数ユーザー向けに常駐させる Streamable HTTP**
運用を主とする。リポ直下に `config/repos.toml` (必須) と必要なら
`config/secrets.toml` を置いた状態で:

```bash
uv run codesearch-mcp serve --transport http --host 127.0.0.1 --port 8000
```

これらの引数を毎回書きたくない場合は `config/server.toml` に書ける
(`transport` / `host` / `port` / `enable_scheduler`)。優先順位は
**CLI > env > `config/server.toml` > 組み込みデフォルト**。同じく
`--repos` / `--secrets` / `--workspace-root` も
**CLI > env > `config/*.toml` 配置 > 組み込みデフォルト** の順で解決される。

クライアント側のエンドポイント: `http://127.0.0.1:8000/mcp/`

> 🔒 HTTP で外部に公開する場合は本サーバ自体に認証機構が無いため、
> リバースプロキシや内部ネットワーク制限で経路を絞ること
> ([`docs/operations.md`](docs/operations.md))。

### 🔌 クライアント側の接続設定

起動した HTTP エンドポイントに対して、MCP クライアントを以下のように
構成する。

#### 🤖 Claude Code

CLI で 1 コマンド登録 (推奨):

```bash
claude mcp add --transport http codesearch http://127.0.0.1:8000/mcp/
```

または `~/.claude/mcp.json` (グローバル) / 対象プロジェクトの `.mcp.json`:

```json
{
  "mcpServers": {
    "codesearch": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp/"
    }
  }
}
```

#### 🖥️ Claude Desktop

`claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/`):

```json
{
  "mcpServers": {
    "codesearch": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp/"
    }
  }
}
```

#### 🦾 Codex CLI

`~/.codex/config.toml` に `[mcp_servers.<name>]` テーブルを追加する。
`url` キーを書いた場合は自動的に HTTP トランスポートになる:

```toml
[mcp_servers.codesearch]
url = "http://127.0.0.1:8000/mcp/"
```

認証ヘッダや bearer token を渡したい場合は `http_headers` /
`bearer_token_env_var` を併用できる。

#### 🧩 OpenCode

`opencode.json` (またはユーザーレベル設定ファイル) に `mcp` セクションを追加:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "codesearch": {
      "type": "remote",
      "url": "http://127.0.0.1:8000/mcp/",
      "enabled": true
    }
  }
}
```

OpenCode では HTTP MCP は `type: "remote"` で指定する
(`type: "local"` は stdio 用)。

#### 🐍 Python `mcp` SDK (自前エージェント)

```python
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("http://127.0.0.1:8000/mcp/") as (r, w, _):
    async with ClientSession(r, w) as session:
        await session.initialize()
        result = await session.call_tool(
            "search_code",
            {"pattern": "class\\s+StreamingResponseBuilder", "repository": "codesearch-mcp-python"},
        )
```

> 🧪 個人開発で **stdio** で立ち上げてクライアント直結したい場合は
> [`docs/installation.md`](docs/installation.md#開発者向け-stdio-でローカル起動する)
> を参照。

---

## 🧪 動作確認 (MCP クライアントを入れずに)

`scripts/probe.py` は MCP ホストアプリ (Claude Code 等) を持たない人や、
サーバが生きているかを CI / 運用で確かめたいケース向けの参照クライアント。
ツールごとの確認手順は
[`scripts/README.ja.md`](scripts/README.ja.md) にまとめている。

```bash
# 🌐 HTTP で常駐させたサーバの公開ツール一覧を取得
uv run python scripts/probe.py --url http://127.0.0.1:8000/mcp/ --list

# ⌨️ stdio でサーバを起動して叩く (起動コマンドは `--` の後)
uv run python scripts/probe.py --stdio -- \
    uv run codesearch-mcp serve --transport stdio

# 🛠️ 任意のツールを実行 (引数は key=value、JSON として解釈)
uv run python scripts/probe.py --url http://127.0.0.1:8000/mcp/ \
    --tool search_code \
    --arg pattern=ToolError \
    --arg repository=codesearch-mcp-python
```

✅ 公開ツール一覧と各 description が表示できれば疎通成功。

---

## 🚨 エラーモデル

ドメインエラーは MCP の `isError: true` ツール結果として返り、`content` の
テキストは以下の JSON 文字列:

```json
{ "code": "REPO_NOT_FOUND", "message": "...", "details": { ... } }
```

代表的なコード:

| 🏷️ コード | 意味 |
| --- | --- |
| 🚫 `REPO_NOT_FOUND` | 指定リポジトリが設定にない |
| ⏳ `REPO_NOT_READY` | 初回 clone が未完了 (時間をおいて再試行) |
| 🛡️ `INVALID_PATH` | パストラバーサルや絶対パスを検出 |
| ❌ `INVALID_PATTERN` | 検索 / グロブパターン不正 |
| 📦 `FILE_TOO_LARGE` / `FILE_BINARY` | `read_file` の対象が読み取れない |
| ⏱️ `TIMEOUT` | サーバ側タイムアウト超過 |

入力スキーマ違反は MCP プロトコル層で `-32602 Invalid params` となる。
全コード一覧は [`docs/spec/spec.md`](docs/spec/spec.md) §5.2。

---

## 🧱 設計のキモ

| 💡 | コンセプト |
| --- | --- |
| 🚫 ベクトル検索なし | `ripgrep` と `git ls-files` で速く・正確に・引用可能 |
| 🔗 引用ファースト | 検索結果は GitHub/GitLab/Bitbucket/Gitea の URL を行アンカー付きで返す |
| 🧯 per-repo 分離 | 1 リポジトリの clone/fetch 失敗が他に波及しない |
| ⛓️ 同期は別経路 | tool call が blocking pull することは禁止 — `codesearch-sync` CLI で分離。完了時に `SIGHUP` で実行中の serve を通知し再起動不要で状態反映 |
| 🛡️ パス安全 | 全パスは `pathsafe` で `..` / 絶対パスを拒否し realpath でリポジトリ内に閉じ込める |
| 🧰 シェル禁止 | サブプロセスは `create_subprocess_exec` のみ。`shell=True` は Ruff S6xx でブロック |

---

## 📚 ドキュメント

- 📥 [`docs/installation.md`](docs/installation.md) — 導入・初期設定
- 🛠️ [`docs/operations.md`](docs/operations.md) — 常設運用・同期戦略・監視
- 📦 [`docs/distribution.md`](docs/distribution.md) — 配布方針 (どの形態で
  入れてどこから繋ぐか)
- 📐 [`docs/spec/spec.md`](docs/spec/spec.md) — 外部仕様 (ツール入出力 /
  エラー / 設定ファイル / 性能保証)
- 🤖 [`docs/usage-for-llm.md`](docs/usage-for-llm.md) — LLM 向け利用ガイダンス
  (capability discovery 文言の原本)
- 🗂️ [`docs/`](docs/) — その他(要件・内部設計・リリース手順 等の
  開発者向け資料)

---

## 📜 ライセンス

MIT
