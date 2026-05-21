# scripts/

開発・運用補助スクリプト群。

## `probe.py` — MCP サーバ動作確認用クライアント

MCP ホスト (Claude Code / Desktop など) を介さずに、起動済みの
`codesearch-mcp` サーバが正しく応答しているかを確認するための最小
クライアント。詳細な用途は `docs/operations.md` 参照。

### 前提

- `codesearch-mcp serve --transport http` が `http://127.0.0.1:8000/mcp/`
  で起動している (別ターミナル)
- 検索対象リポジトリが clone 済み (`uv run codesearch-sync` を 1 回以上実行)

### 確認順序

依存の浅い順 (引数なし → 引数あり → ファイル内容まで) に並べてある。
途中で `isError: True` が返ってきたら、そこで止めて応答 JSON を確認する。

#### 1. ツール一覧の取得 (疎通確認)

サーバが上がっており initialize / listTools が返ることを確認する。

```bash
uv run python scripts/probe.py --url http://127.0.0.1:8000/mcp/ --list
```

期待: 5 ツール (`search_code` / `list_files` / `list_tree` / `read_file`
/ `list_repositories`) が description 付きで列挙される。

#### 2. `list_repositories` — リポジトリカタログ

引数を取らない discovery ツール。設定済みリポジトリの id と state を確認する。

```bash
uv run python scripts/probe.py --url http://127.0.0.1:8000/mcp/ \
    --tool list_repositories
```

期待: `repositories[].id` と `repositories[].status.state` が `"ready"`。
`uninitialized` の場合は sync が走っていないか、サーバ起動が sync より
前で SIGHUP 通知も届いていない (= サーバを別ターミナルで再起動するか、
もう一度 `codesearch-sync` を実行)。

#### 3. `list_tree` — ディレクトリ俯瞰

リポジトリの構造を見る。`max_depth` で深さ制限。

```bash
uv run python scripts/probe.py --url http://127.0.0.1:8000/mcp/ \
    --tool list_tree \
    --arg repository=codesearch-mcp-python \
    --arg max_depth=1
```

期待: `tree` フィールドに ASCII ツリー、`truncated: false`。

#### 4. `list_files` — ファイル名で検索

glob でファイルを引く。

```bash
uv run python scripts/probe.py --url http://127.0.0.1:8000/mcp/ \
    --tool list_files \
    --arg repository=codesearch-mcp-python \
    --arg pattern='src/**/__init__.py'
```

期待: `files[]` に複数件、各エントリに `file_path` / `last_modified` /
`git_url` (行アンカー `#L1` 付き)。

#### 5. `search_code` — ファイル内容を正規表現で検索

ヒット件数が多いパターンで `truncated` の挙動も確認する。

```bash
uv run python scripts/probe.py --url http://127.0.0.1:8000/mcp/ \
    --tool search_code \
    --arg pattern=ToolError \
    --arg repository=codesearch-mcp-python \
    --arg max_results=5
```

期待: `matches[]` に 5 件、`truncated: true`、`total_matches` に実際の
ヒット総数。各 match に `git_url` が行アンカー (`#L<line>`) 付き。

#### 6. `read_file` — ファイル内容の行範囲取得

`search_code` で得た `file_path` / `line_number` を読み出す。

```bash
uv run python scripts/probe.py --url http://127.0.0.1:8000/mcp/ \
    --tool read_file \
    --arg repository=codesearch-mcp-python \
    --arg file_path=src/codesearch_mcp/server.py \
    --arg start_line=90 \
    --arg num_lines=20
```

期待: `content` に行番号付きの該当範囲、`git_url` に範囲アンカー
(`#L90-L109`) 付き。

### エラー時の確認ポイント

| エラーコード | 主な原因 |
| --- | --- |
| `REPO_NOT_FOUND` | `--arg repository=...` の id が `config/repos.toml` に無い |
| `REPO_NOT_READY` | sync 未実施 / サーバ起動後に sync したが SIGHUP が届いていない |
| `INVALID_PATH` | `read_file` の `file_path` が `..` / 絶対パスを含む |
| `INVALID_PATTERN` | 正規表現 / glob として不正 |
| `FILE_TOO_LARGE` / `FILE_BINARY` | `read_file` の対象が 10MiB 超 / UTF-8 でない |
| `TIMEOUT` | サーバ側で 30 秒超過 |

接続エラー (`httpx.ConnectError` 等) はサーバ未起動。
`lsof -i :8000` でリッスン状態を確認。
