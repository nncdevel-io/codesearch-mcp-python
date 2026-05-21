# Code Search MCP Server — 設計(アーキテクチャ)

本書は要件書 (`docs/requirements.md`) と仕様書 (`docs/spec/spec.md`) を
受けて、内部実現のアーキテクチャレベルの設計を定義する。関数
シグネチャや細部のエッジ処理は各実装タスク (TDD) の中で決める。

作成日: 2026-05-19

## 1. 確定した方針

| 論点 | 決定 | 根拠 |
| --- | --- | --- |
| 完成範囲 | 全機能を段階的に完成 (P0〜P8) | 利用者選択 |
| 設計の扱い | アーキテクチャ設計のみ本書に記し、詳細設計は各 TDD タスク内 | 利用者選択 |
| テスト | TDD (テスト先行)。単体 + 結合 | 利用者選択 |
| MCP フレームワーク | 公式 `mcp` Python SDK (FastMCP) | MCP 仕様準拠と stdio/Streamable HTTP 両対応の要件上、唯一の妥当解 |
| 並行モデル | 全体 async。外部コマンドは `asyncio.create_subprocess_exec` | シェル非経由でインジェクション耐性、並列走査の利得 |
| Git 同期 | リクエストパスから完全分離。デプロイ非依存 | 利用者選択。要件 5.1/5.2 と整合 |
| スケジューラ | 素の asyncio ループ。任意コンポーネント (ON/OFF) | 固定間隔更新に APScheduler 等は YAGNI |
| Tool description の粒度 | `tools/list` で配信する description は 600〜1,000 chars / ツールの厚めの記述を採用 (Tips / 隣接ツールへの cross-reference / エラー条件まで含む)。LLM のツール選択精度を優先 | 前提: ホスト LLM が 100K+ コンテキストクラス (`docs/operations.md` 「ホスト LLM のコンテキスト窓」)。回帰: `tests/test_tool_descriptions.py` |

## 2. Git 同期アーキテクチャ (デプロイ非依存)

同期は冪等なスタンドアロン操作とし、ツール (検索) 側は常に
ローカルワークスペースを読むだけ。両者は独立しており、同期
トリガが何であってもアーキテクチャは不変。

トリガは 3 系統を提供する。

1. **`codesearch-sync` CLI サブコマンド** — 全リポジトリまたは
   指定リポジトリを 1 回同期して終了。cron / systemd timer /
   Kubernetes CronJob / CI から起動可能 (要件 4.5.2 を外部
   定期実行で満たす経路)
2. **任意の in-process スケジューラ** — 設定で ON/OFF。常駐
   デプロイ時のみ有効化し、要件 4.5.2 をプロセス内で満たす
3. **任意のリクエスト側 staleness ガード** — 最終同期から
   既定 TTL 超過時、応答はローカルワークスペースで即返し、
   更新は *応答後に非ブロッキングで* キュー投入。リクエスト
   処理をブロックしないため要件 5.1 (p95 2 秒) を侵さない

> 同期的なリクエスト時 git pull は、`git fetch` が秒オーダーに
> なり得るため要件 5.1/5.2 に抵触する。本設計では採らない。

clone/fetch/reset・readiness 状態管理・障害分離 (個別リポジトリ
失敗が他に波及しない) のコア実装は共通モジュールに置き、上記
3 トリガはその薄い起動口とする。

## 3. モジュール構成 (`src/codesearch_mcp/`)

| モジュール | 責務 |
| --- | --- |
| `__main__.py` | CLI。`serve --transport stdio\|http` と `sync` サブコマンド、起動時検証、依存配線 |
| `config/models.py` | repos.toml / secrets.toml の Pydantic モデル |
| `config/loader.py` | 読込と起動時検証 (TOML パース / 必須 / `id` 一意 / `hosting` enum / 秘密ファイル権限 600 以下) |
| `repo/manager.py` | リポジトリ登録、ワークスペースパス、readiness 状態、最終同期状況 |
| `repo/git_sync.py` | clone (`--branch --single-branch`)、fetch、`reset --hard`、認証 (token/ssh_key/none)、リポジトリ単位の障害分離 |
| `repo/scheduler.py` | 任意の asyncio 定期更新ループ、次 tick リトライ |
| `backends/command.py` | 非同期サブプロセス実行、タイムアウト、`BACKEND_FAILURE` 写像 |
| `backends/ripgrep.py` | `rg` argv 構築と `--json` 出力パース (search_code / list_files) |
| `backends/git_ls.py` | `git ls-files` 実行 |
| `tools/search_code.py` | content / files_with_matches / count の組立、max_results 丸め、truncated |
| `tools/list_files.py` | グロブ列挙、`last_modified` 降順 |
| `tools/list_tree.py` | git ls-files からツリー整形 (max_depth / max_entries / show_files、Unicode 罫線、コードポイント順) |
| `tools/read_file.py` | 純 Python 範囲読み取り、サイズ (>10MB→`FILE_TOO_LARGE`)・バイナリ (`FILE_BINARY`) 判定、行番号タブ整形 |
| `pathsafe.py` | 相対パス検証 (絶対 / `..` 拒否、realpath 封じ込め) → `INVALID_PATH` / `PATH_NOT_FOUND` |
| `giturl.py` | hosting 別 URL 生成 (github/gitlab/bitbucket/gitea、単一・範囲、URL エンコード規則) |
| `errors.py` | エラーコード、`{code,message,details}` 直列化、`isError` 結果。秘密情報・スタックトレース非出力 |
| `server.py` | FastMCP アプリ、5 ツール (4 検索 + `list_repositories`) 登録、`capabilities.prompts` 抑止、Resources 登録、並列セマフォ(16)、ツール別タイムアウト、全体 30 秒 |
| `logging.py` | 構造化ログ、秘密情報秘匿 |
| `observability.py` | 各リポジトリの最終同期時刻・結果の参照 |

## 4. データフロー (ツール呼び出し)

1. トランスポートが `tools/call` 受信 → FastMCP が inputSchema
   検証 (違反は `-32602 Invalid params`)
2. サーバラッパ: 並列セマフォ取得 (上限 16。キュー待ち+実行が
   30 秒超で `TIMEOUT`)、ツール別タイムアウト開始
   (search 10s / list_files 5s / list_tree 5s / read_file 3s)
3. リポジトリ解決: 未設定 `REPO_NOT_FOUND` / 未 clone `REPO_NOT_READY`
4. パス検証 (pathsafe): 絶対・`..` で `INVALID_PATH`、不在で `PATH_NOT_FOUND`
5. ツール処理 (ripgrep / git ls-files / 純 Python)
6. `git_url` 付与 (単一行、または context 指定時は範囲アンカー)
7. 仕様 outputSchema で返却。ドメインエラーは `isError:true` +
   JSON 文字列 `{code,message,details}`

## 5. 非機能の実装方針

- **性能**: 全体 async、外部コマンド並列、`asyncio.wait_for` で
  タイムアウト。同期はリクエストパス外
- **可用性**: 起動時に同期完了を待たず既存ワークスペースで応答。
  個別リポジトリの取得失敗を分離
- **信頼性**: 同期失敗はログし次回再試行。原因判別可能なエラー
  コードを返す
- **セキュリティ**: pathsafe で realpath 封じ込め、未設定
  リポジトリ拒否、秘密情報非ログ、push 権限不要、シェル非経由
- **運用性**: 起動・同期・ツール呼び出しの構造化ログ、最終
  同期状況の参照手段

## 6. テスト戦略 (TDD)

- **単体**: pathsafe / giturl (4 hosting × 単一・範囲・エンコード) /
  rg argv・JSON パース / list_tree 整形 (深さ・件数・整列・罫線) /
  read_file 行番号・binary・サイズ / config 検証 / エラー直列化
- **結合**: 一時 git リポジトリ (及びローカル bare を "remote"
  扱い) を fixture 化し、FastMCP インメモリクライアントで各
  ツールと同期 (CLI 経路含む) を端点間検証。`rg`/`git` 必須、
  無ければ明示スキップ
- 各単位は red → green → refactor

## 7. フェーズ分割 (実行計画の骨格)

| フェーズ | 内容 |
| --- | --- |
| **P0** | 雛形 (uv / pyproject / レイアウト / lint / pytest) + errors・pathsafe・giturl (純粋関数、完全 TDD) |
| **P1** | config モデル・読込・起動時検証 + example ファイル |
| **P2** | RepositoryManager + git_sync (clone/fetch/reset/認証/障害分離) + readiness |
| **P3** | command runner + ripgrep ラッパ |
| **P4** | tools (read_file → search_code → list_files → list_tree、各 TDD) |
| **P5** | FastMCP 配線、4 ツール登録、並列/タイムアウト/キュー、エラー形式、`-32602` 通過 |
| **P6** | 同期トリガ整備: `codesearch-sync` CLI + 任意 in-process スケジューラ + 任意 staleness ガード、構造化ログ、observability |
| **P7** | トランスポート (stdio + Streamable HTTP / CLI フラグ)、両端点間テスト、README/運用手順整備 |
| **P8** | 性能サニティ (大規模スモーク) + 要件/仕様チェックリスト自己レビュー |

詳細タスクは本設計を入力として writing-plans で展開する。
