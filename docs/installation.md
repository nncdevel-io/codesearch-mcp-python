# インストール

`codesearch-mcp` をローカルで動かすための手順をまとめる。
本サーバーは MCP クライアント (Claude Code、Claude Desktop、自前の
チャットアプリなど) から呼び出される常駐プロセスとして動く。

## 前提

- Linux または macOS
- Python 3.11 以上
- `git` と `ripgrep` (`rg`) が PATH 上に存在すること
- パッケージ管理は [uv](https://docs.astral.sh/uv/) を使う
  (本リポジトリで `pip` は使わない)

```bash
git --version
rg --version | head -1
uv --version
```

これら 3 つが揃っていない環境では、後続の `uv sync` 後でも結合テストや
実際の検索処理が動かない。

## 手順

```bash
git clone https://github.com/<owner>/codesearch-mcp-python
cd codesearch-mcp-python
uv sync --frozen
```

`--frozen` は `uv.lock` のバージョンを厳密に適用する。動作確認:

```bash
uv run codesearch-mcp --help
uv run codesearch-sync --help
```

`codesearch-mcp` は MCP サーバ本体、`codesearch-sync` はリポジトリを
ワンショットで同期する CLI。

## 設定ファイルの配置

利用者が用意するのは以下の 2 ファイル。例は `examples/` を参照。

| ファイル | 内容 | パーミッション |
| --- | --- | --- |
| `repos.toml` | 検索対象リポジトリ (ID / リモート URL / ブランチ / ホスティング種別) | 任意 (機密ではない) |
| `secrets.toml` | 認証情報 (token / SSH 鍵パス)。**必須でない** (公開リポジトリのみなら不要) | **600 必須** |

`secrets.toml` のパーミッションが 600 より緩い場合、サーバ起動は中断される。

```bash
cp config/repos.toml.example ./repos.toml
cp config/secrets.toml.example ./secrets.toml
chmod 600 ./secrets.toml
$EDITOR ./repos.toml ./secrets.toml
```

## リポジトリ description の設計

`repos.toml` の各リポジトリには description フィールドを書く
(本サーバーが `resources/list` および `list_repositories` の応答に
そのまま載せる)。これは AI エージェントが「ユーザーの質問に対して
どのリポジトリを検索すべきか」を判断する唯一の手掛かりであり、
サーバー実装側から自動生成・補正はできない。**初期セットアップ時に
書き、リポジトリを追加するたびに書く**運用前提の項目である。

判断フローと位置付けは `docs/agent-sequence.md` §3〜§4 を参照。
本節は書き方の指針を提示する。

### ボリュームの目安

- 推奨: **1〜3 文、60〜200 文字**程度。
- 全リポジトリの description はホストの実装によっては LLM の
  システムプロンプト相当のコンテキストにまとめて載る。件数が多いと
  総量が無視できない。50 リポジトリで平均 150 文字なら約 7,500 文字
  であり、これを超え始める前に内容を絞り込む。
- 短すぎる (例: 「バックエンド」のみ) と兄弟リポジトリと区別がつかず、
  エージェントが誤選択するか並列探索コストを払う。
- 長すぎる (4 文以上の説明的散文) と要点が薄まり、キーワード照合の
  ヒット率が下がる。

### 含めるべき 4 要素

| 要素 | 役割 | 例 |
| --- | --- | --- |
| レイヤー / 種別 | 「どこの層か」を 1 語で示す | Frontend SPA / Backend API / Mobile (iOS) / Infra (Terraform) / Shared library |
| 言語・主要フレームワーク | 技術質問とのマッチに直結 | Python + FastAPI / TypeScript + React / Go / Java + Spring Boot |
| 担当ドメインの代表キーワード | ユーザー発話との単語一致を作る | 決済・認証・通知 / 商品検索・在庫 / 顧客管理・契約 |
| 兄弟リポジトリとの境界 | 誤選択を能動的に防ぐ | UI は `foo` を参照 / 共通型は `shared-types` を参照 |

「担当ドメインの代表キーワード」は、ユーザー質問に登場しうる名詞
そのものを含めるのが効く (LLM はそれを手掛かりに照合する)。
逆に社内独自の略号だけにすると、自然言語質問とマッチしにくい。

### 含めない要素

- 履歴的経緯 (「2024 年に分割」「旧 X プロジェクト」など)
- 担当チーム名・人名 (鮮度が落ちやすく、選択判断に寄与しない)
- 詳細な API リストやファイル構成 (`list_tree` で取得できる)
- 内部実装の事情 (DB 種別、CI 環境など、選択精度に寄与しない情報)
- 機微情報 (URL の認証情報、内部ホスト名など)

### 良い例 / 悪い例

**良い例** (約 90 文字、4 要素を全て含む):

```text
Backend API. Python + FastAPI. 決済・認証・通知・Webhook のドメイン
ロジック。UI は foo、共通型は shared-types を参照。
```

**短すぎる例:**

```text
バックエンド
```

→ 言語・ドメイン・境界が欠落。`bar-api` と `bar-batch` を分けても
区別できない。

**冗長な例:**

```text
本リポジトリは MyCompany の基幹システムの中核をなすバックエンド
サービスであり、ユーザー登録から認証、決済、通知、レポーティングまで
広範な機能を提供しており、長年に渡り社内で運用されている重要な
コンポーネントです。
```

→ 1 文目で言語・フレームワークが出ず、後半で要点が薄まる。
読了に要する文量に対して識別情報が乏しい。

### 同種リポジトリが多い場合の書き分け

`bar-api` / `bar-batch` / `bar-admin` のように同じドメインを複数
リポジトリで分担している場合、各 description の冒頭で
**役割の差** を 1 語で識別できるように書く。

```text
Backend (request 層). Python + FastAPI. 同期 API のリクエスト処理と
レスポンスシリアライズ。バッチは bar-batch、管理画面は bar-admin を参照。
```

```text
Backend (batch 層). Python + Celery. 夜次集計・通知キューの非同期処理。
同期 API は bar-api を参照。
```

冒頭の括弧書きで「どの層か」を明示することで、ユーザーが「決済の
夜間集計」と尋ねた場合に `bar-batch` を、「決済 API のエラー応答」と
尋ねた場合に `bar-api` を、それぞれ第一候補として選びやすくなる。

### セットアップ時のチェックリスト

`repos.toml` を最初に書く / リポジトリを追加するときに以下を確認する。

- [ ] 各 description が 60〜200 文字に収まっているか
- [ ] レイヤー / 言語 / ドメインキーワード / 境界 の 4 要素が
      入っているか (兄弟リポジトリがなければ境界は省略可)
- [ ] ユーザーが自然言語で発する語が少なくとも 1 つ含まれているか
- [ ] 同種の兄弟がある場合、冒頭で役割の差が示されているか
- [ ] 機微情報・人名・履歴的経緯が含まれていないか

## 環境変数

| 変数 | 用途 | 既定値 |
| --- | --- | --- |
| `CODE_SEARCH_REPOS_PATH` | `repos.toml` のパス | (引数 `--repos` で指定) |
| `CODE_SEARCH_SECRETS_PATH` | `secrets.toml` のパス | (省略時は匿名アクセス) |
| `CODE_SEARCH_WORKSPACE_ROOT` | ワークスペースルート | `./workspaces` |
| `CODE_SEARCH_LOG_LEVEL` | ログレベル | `INFO` |

CLI フラグ (`--repos` / `--secrets` / `--workspace-root`) が指定された場合は
そちらが優先される。

## 初回同期

最初の `git clone` をしておくと、サーバ起動直後から検索が可能になる。

```bash
uv run codesearch-sync \
    --repos ./repos.toml \
    --secrets ./secrets.toml \
    --workspace-root ./workspaces
```

出力は各リポジトリの成否を JSON で返す。すべて成功すれば終了コード 0。

## 開発者向け: stdio でローカル起動する

本サーバの主たる運用形態はチーム共用の常駐 HTTP サーバである
(README および `docs/operations.md` を参照)。一方で、開発者個人が
ローカルで Claude Code / Claude Desktop に直結したい場合は **stdio**
トランスポートで起動できる。MCP クライアントが子プロセスとして
本サーバを起動し、stdin/stdout で JSON-RPC をやり取りする。

### Claude Code

`~/.claude/mcp.json` または対象プロジェクトの `.mcp.json` に追記する:

```json
{
  "mcpServers": {
    "codesearch": {
      "command": "uv",
      "args": [
        "run", "--directory", "/path/to/codesearch-mcp-python",
        "codesearch-mcp", "serve", "--transport", "stdio",
        "--repos", "/path/to/repos.toml",
        "--secrets", "/path/to/secrets.toml",
        "--workspace-root", "/path/to/workspaces"
      ]
    }
  }
}
```

### Claude Desktop

`claude_desktop_config.json` (macOS では
`~/Library/Application Support/Claude/`):

```json
{
  "mcpServers": {
    "codesearch": {
      "command": "uv",
      "args": [
        "run", "--directory", "/path/to/codesearch-mcp-python",
        "codesearch-mcp", "serve", "--transport", "stdio",
        "--repos", "/path/to/repos.toml"
      ],
      "env": {
        "CODE_SEARCH_SECRETS_PATH": "/path/to/secrets.toml",
        "CODE_SEARCH_WORKSPACE_ROOT": "/path/to/workspaces"
      }
    }
  }
}
```

### 注意

- stdio 起動はクライアントごとに別プロセスが立ち上がる。複数ユーザー /
  複数クライアントから共用したい場合は HTTP サーバとして常駐させる
  (README の「サーバー起動」節)。
- 認証情報を含む `secrets.toml` を `env` で渡す場合、設定ファイル自体が
  600 権限であることを確認する (本ドキュメント上部「設定ファイルの配置」)。
- stdio モードでは標準入出力が JSON-RPC で占有されるため、ログは
  stderr に出力される。`CODE_SEARCH_LOG_LEVEL` で制御する。

## devcontainer

VS Code / Codespaces 経由の場合は `.devcontainer/devcontainer.json` が
利用できる。Python 3.13 + uv + ripgrep + git + Node (markdownlint 用)
が `postCreateCommand` で揃う。
