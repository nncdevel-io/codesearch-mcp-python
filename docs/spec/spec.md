# Code Search MCP Server — 仕様書

本書は Code Search MCP Server の外部仕様を定義する。

要件書 (`requirements.md`) で定めた「何を提供するか」を受けて、
クライアントから観察可能なインターフェースを厳密に規定する。
内部の実現方法 (モジュール構成、依存性注入、スケジューラ実装など)
は設計書の責務とし、本書では扱わない。

## 1. 本書の位置付け

| 文書 | 視点 | 内容 |
| --- | --- | --- |
| 要件書 | 何を解決するか | スコープ、機能要件、非機能要件、外部依存の選定 |
| 仕様書 (本書) | 何を提供するか | プロトコル準拠、ツール入出力、エラー、設定 |
| 設計書 | どう実現するか | モジュール、データフロー、内部構造 |

本書の対象読者は、本サーバーを利用する MCP クライアント開発者、
本サーバーの実装者、運用者である。

## 2. MCP プロトコル準拠

本サーバーは Model Context Protocol の公式仕様
([MCP Specification](https://spec.modelcontextprotocol.io/))
に準拠する。プロトコル固有の事項
(JSON-RPC 2.0 メッセージ構造、初期化シーケンス、capability negotiation
など) は公式仕様に委ね、本書ではサーバー固有のツール仕様を規定する。

### 2.1 サポートするトランスポート

| トランスポート | 用途 |
| --- | --- |
| stdio | ローカル実行、Claude Code 等のデスクトップエージェント |
| Streamable HTTP | リモートデプロイ、Web チャットアプリケーション |

起動時のオプションでどちらを使うかを選択する。
同一プロセスで両方を同時に提供することはしない。

### 2.2 公開する capability

本サーバーは `tools` capability と `resources` capability を公開する。
`prompts` および `sampling` は公開しない。

`resources` capability の用途は、設定済みリポジトリのカタログを
クライアント (LLM) から discovery 可能にすることである。詳細は §4.5
を参照。

### 2.3 公開するツール一覧

| ツール名 | 概要 |
| --- | --- |
| `search_code` | ファイル内容のパターン検索 |
| `list_files` | ファイル名パターンによるファイル列挙 |
| `list_tree` | ディレクトリ階層の俯瞰 |
| `read_file` | 指定範囲のファイル内容読み取り |
| `list_repositories` | 設定済みリポジトリのカタログを返す (Resources 非対応ホスト向けの discovery) |

## 3. 共通データ型

複数のツールで共通して使用するスキーマを定義する。

### 3.1 リポジトリ識別子

```json
{
  "type": "string",
  "pattern": "^[a-zA-Z0-9._-]+$",
  "minLength": 1,
  "maxLength": 64,
  "description": "設定ファイルで定義されたリポジトリの一意な識別子"
}
```

### 3.2 相対パス

```json
{
  "type": "string",
  "minLength": 0,
  "maxLength": 4096,
  "description": "リポジトリルートからの相対パス。POSIX形式 (区切り文字は /)。先頭の / および .. の使用は禁止"
}
```

絶対パスの指定、および `..` を含むパスは `INVALID_PATH` エラーで
拒否する。空文字列はリポジトリルートを指す。

### 3.3 Git URL

```json
{
  "type": "string",
  "format": "uri",
  "description": "Gitホスティングサービス上の該当箇所へのURL。行番号アンカー付き"
}
```

URL 生成規則は 6 章を参照。

## 4. ツール仕様

### 4.1 search_code

ファイル内容に対するパターン検索を行う。

#### 4.1.1 inputSchema

```json
{
  "type": "object",
  "properties": {
    "pattern": {
      "type": "string",
      "minLength": 1,
      "maxLength": 1024,
      "description": "検索パターン。Rust regex crateの構文 (look-around非対応)"
    },
    "repository": { "$ref": "#/$defs/repository" },
    "path": { "$ref": "#/$defs/relativePath" },
    "glob": {
      "type": "string",
      "maxLength": 256,
      "description": "ファイル名のグロブパターン"
    },
    "type": {
      "type": "string",
      "description": "ripgrep --type で指定可能な言語種別"
    },
    "case_sensitive": {
      "type": "boolean",
      "default": false
    },
    "output_mode": {
      "type": "string",
      "enum": ["content", "files_with_matches", "count"],
      "default": "content"
    },
    "context_before": {
      "type": "integer",
      "minimum": 0,
      "maximum": 20,
      "default": 0
    },
    "context_after": {
      "type": "integer",
      "minimum": 0,
      "maximum": 20,
      "default": 0
    },
    "max_results": {
      "type": "integer",
      "minimum": 1,
      "maximum": 500,
      "default": 50
    }
  },
  "required": ["pattern", "repository"],
  "additionalProperties": false
}
```

#### 4.1.2 outputSchema (content モード)

```json
{
  "type": "object",
  "properties": {
    "matches": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "repository": { "type": "string" },
          "file_path": { "type": "string" },
          "line_number": { "type": "integer", "minimum": 1 },
          "line_content": { "type": "string" },
          "context_before": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "line_number": { "type": "integer" },
                "content": { "type": "string" }
              }
            }
          },
          "context_after": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "line_number": { "type": "integer" },
                "content": { "type": "string" }
              }
            }
          },
          "git_url": { "type": "string", "format": "uri" }
        },
        "required": ["repository", "file_path", "line_number",
                     "line_content", "git_url"]
      }
    },
    "truncated": { "type": "boolean" },
    "total_matches": { "type": "integer" }
  },
  "required": ["matches", "truncated", "total_matches"]
}
```

#### 4.1.3 outputSchema (files_with_matches モード)

```json
{
  "type": "object",
  "properties": {
    "files": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "repository": { "type": "string" },
          "file_path": { "type": "string" },
          "git_url": { "type": "string", "format": "uri" }
        },
        "required": ["repository", "file_path", "git_url"]
      }
    },
    "truncated": { "type": "boolean" }
  },
  "required": ["files", "truncated"]
}
```

#### 4.1.4 outputSchema (count モード)

```json
{
  "type": "object",
  "properties": {
    "files": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "repository": { "type": "string" },
          "file_path": { "type": "string" },
          "match_count": { "type": "integer", "minimum": 1 },
          "git_url": { "type": "string", "format": "uri" }
        },
        "required": ["repository", "file_path", "match_count",
                     "git_url"]
      }
    },
    "truncated": { "type": "boolean" }
  },
  "required": ["files", "truncated"]
}
```

#### 4.1.5 呼び出し例

入力:

```json
{
  "pattern": "class\\s+StreamingResponseBuilder",
  "repository": "main-app",
  "glob": "**/*.java",
  "max_results": 10
}
```

出力 (一部省略):

```json
{
  "matches": [
    {
      "repository": "main-app",
      "file_path": "src/main/java/com/example/StreamingResponseBuilder.java",
      "line_number": 42,
      "line_content": "public final class StreamingResponseBuilder {",
      "git_url": "https://github.com/example/main-app/blob/main/src/main/java/com/example/StreamingResponseBuilder.java#L42"
    }
  ],
  "truncated": false,
  "total_matches": 1
}
```

### 4.2 list_files

ファイル名パターンに一致するファイルを列挙する。

#### 4.2.1 inputSchema

```json
{
  "type": "object",
  "properties": {
    "repository": { "$ref": "#/$defs/repository" },
    "pattern": {
      "type": "string",
      "minLength": 1,
      "maxLength": 256,
      "description": "グロブパターン (例: **/*.java)"
    },
    "path": { "$ref": "#/$defs/relativePath" },
    "max_results": {
      "type": "integer",
      "minimum": 1,
      "maximum": 500,
      "default": 100
    }
  },
  "required": ["repository", "pattern"],
  "additionalProperties": false
}
```

#### 4.2.2 outputSchema

```json
{
  "type": "object",
  "properties": {
    "files": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "repository": { "type": "string" },
          "file_path": { "type": "string" },
          "last_modified": {
            "type": "string",
            "format": "date-time"
          },
          "git_url": { "type": "string", "format": "uri" }
        },
        "required": ["repository", "file_path",
                     "last_modified", "git_url"]
      }
    },
    "truncated": { "type": "boolean" }
  },
  "required": ["files", "truncated"]
}
```

結果は `last_modified` の降順で返す。

### 4.3 list_tree

ディレクトリ階層を俯瞰するためのツリー表現を返す。

#### 4.3.1 inputSchema

```json
{
  "type": "object",
  "properties": {
    "repository": { "$ref": "#/$defs/repository" },
    "path": { "$ref": "#/$defs/relativePath" },
    "max_depth": {
      "type": "integer",
      "minimum": 1,
      "maximum": 5,
      "default": 2
    },
    "show_files": {
      "type": "boolean",
      "default": true
    },
    "max_entries": {
      "type": "integer",
      "minimum": 1,
      "maximum": 1000,
      "default": 200
    }
  },
  "required": ["repository"],
  "additionalProperties": false
}
```

#### 4.3.2 outputSchema

```json
{
  "type": "object",
  "properties": {
    "repository": { "type": "string" },
    "root_path": { "type": "string" },
    "tree": {
      "type": "string",
      "description": "ASCIIアート形式のツリー表現"
    },
    "truncated": { "type": "boolean" },
    "entry_count": { "type": "integer", "minimum": 0 }
  },
  "required": ["repository", "root_path", "tree",
               "truncated", "entry_count"]
}
```

#### 4.3.3 tree フィールドのフォーマット

ツリー表現は以下の形式とする。

```text
src/
├── main/
│   ├── java/
│   │   └── com/
│   │       └── example/
│   └── resources/
└── test/
    └── java/
```

- インデントは半角空白
- 罫線は Unicode 罫線素片 (`├`, `└`, `│`, `─`)
- ディレクトリ名は末尾に `/` を付与
- エントリは名前順 (ロケール非依存の Unicode コードポイント順)

### 4.4 read_file

指定したファイルの指定行範囲を読み取る。

#### 4.4.1 inputSchema

```json
{
  "type": "object",
  "properties": {
    "repository": { "$ref": "#/$defs/repository" },
    "file_path": { "$ref": "#/$defs/relativePath" },
    "start_line": {
      "type": "integer",
      "minimum": 1,
      "default": 1
    },
    "num_lines": {
      "type": "integer",
      "minimum": 1,
      "maximum": 2000,
      "default": 100
    }
  },
  "required": ["repository", "file_path"],
  "additionalProperties": false
}
```

#### 4.4.2 outputSchema

```json
{
  "type": "object",
  "properties": {
    "repository": { "type": "string" },
    "file_path": { "type": "string" },
    "start_line": { "type": "integer", "minimum": 1 },
    "end_line": { "type": "integer", "minimum": 1 },
    "total_lines": { "type": "integer", "minimum": 0 },
    "content": {
      "type": "string",
      "description": "行番号プレフィックス付きのファイル内容"
    },
    "git_url": { "type": "string", "format": "uri" }
  },
  "required": ["repository", "file_path", "start_line",
               "end_line", "total_lines", "content", "git_url"]
}
```

#### 4.4.3 content フィールドのフォーマット

各行に「行番号 + タブ文字 (`\t`, U+0009) + 内容」のプレフィックスを
付与する。行番号は右寄せ、幅は `end_line` の桁数に合わせる。

例 (start_line=40, num_lines=3、`→` はタブ文字を表す):

```text
  40→public final class StreamingResponseBuilder {
  41→    private final OutputStream out;
  42→    private final Charset charset;
```

#### 4.4.4 ファイルサイズ制約

ファイル全体のサイズが 10 MB を超える場合は `FILE_TOO_LARGE`
エラーを返す。`start_line` と `num_lines` で範囲を絞っても、
ファイル全体のサイズ判定が先行する。

#### 4.4.5 バイナリ判定

ファイルがテキストとして解釈できない (NUL バイトを含む、
UTF-8 として無効など) 場合は `FILE_BINARY` エラーを返す。

### 4.5 list_repositories

設定済みリポジトリのカタログを返す。`resources/list` および
`resources/read` と同じ情報をツール経路でも取得できるようにすることで、
Resources を LLM 文脈に注入しない MCP ホスト (現行 Claude Desktop の
一部実装など) でもリポジトリ ID を発見可能にする。

#### 4.5.1 inputSchema

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

引数なし。

#### 4.5.2 outputSchema

```json
{
  "type": "object",
  "properties": {
    "repositories": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": { "type": "string" },
          "branch": { "type": "string" },
          "hosting": {
            "type": "string",
            "enum": ["github", "gitlab", "bitbucket", "gitea"]
          },
          "hosting_base_url": { "type": "string" },
          "exclude_paths": {
            "type": "array",
            "items": { "type": "string" }
          },
          "refresh_interval_seconds": { "type": "integer" },
          "description": { "type": ["string", "null"] },
          "status": {
            "type": "object",
            "properties": {
              "repository": { "type": "string" },
              "state": {
                "type": "string",
                "enum": ["uninitialized", "ready", "failed"]
              },
              "last_outcome": {
                "type": ["string", "null"],
                "enum": ["success", "failure", null]
              },
              "last_sync_at": { "type": ["string", "null"], "format": "date-time" },
              "last_commit": { "type": ["string", "null"] },
              "last_error": { "type": ["string", "null"] }
            },
            "required": [
              "repository", "state", "last_outcome",
              "last_sync_at", "last_commit", "last_error"
            ]
          }
        },
        "required": [
          "id", "branch", "hosting", "hosting_base_url",
          "exclude_paths", "refresh_interval_seconds",
          "description", "status"
        ]
      }
    }
  },
  "required": ["repositories"]
}
```

#### 4.5.3 挙動

- 並び順は設定ファイル `repos.toml` の記述順 (= サーバ内部の登録順)
- `status` フィールドの内容は時刻依存。クライアントは呼び出しのたびに
  最新値を取得すべきで、長時間キャッシュしない (§4.6.4 と同じ注意)

### 4.6 リポジトリ Resource

設定済みリポジトリは MCP の Resource として広告する。これにより
クライアント (LLM) は `resources/list` を呼び出すだけで、有効な
`repository` 引数の集合を発見できる。

#### 4.6.1 URI 規約

```text
codesearch://repo/{id}
```

`{id}` は設定ファイル (`repos.toml`) の `id` フィールドの値で、
§3.1 のパターン (`^[a-zA-Z0-9._-]+$`) を満たす。

#### 4.6.2 `resources/list`

設定されたリポジトリすべてを次の形で返す。

| フィールド | 値 |
| --- | --- |
| `uri` | `codesearch://repo/{id}` |
| `name` | `Repository: {id}` (人間可読のラベル) |
| `title` | `{id}` (短縮ラベル) |
| `description` | 1〜2 文の説明 (用途・読み取り内容の概略) |
| `mimeType` | `application/json` |

#### 4.6.3 `resources/read`

指定 URI の中身として、以下の JSON オブジェクトを 1 つの
`text` Content として返す。

```json
{
  "id": "main-app",
  "branch": "main",
  "hosting": "github",
  "hosting_base_url": "https://github.com/example/main-app",
  "exclude_paths": ["docs/generated/", "vendor/"],
  "refresh_interval_seconds": 900,
  "description": "Backend service for the main customer-facing app. FastAPI + SQLAlchemy. Key dirs: billing/, auth/, models/.",
  "status": {
    "repository": "main-app",
    "state": "ready",
    "last_outcome": "success",
    "last_sync_at": "2026-05-20T01:23:45Z",
    "last_commit": "deadbeef…",
    "last_error": null
  }
}
```

- `description` は運用者が `repos.toml` に記述した自由文。設定で
  指定されていない場合は `null`
- `status.state` は `uninitialized` / `ready` / `failed`
- `status.last_outcome` は `success` / `failure` / `null`
- `status.last_sync_at` は ISO 8601 (UTC, 末尾 `Z`)、未同期は `null`
- `status.last_error` は最後の失敗メッセージ。直近が成功なら `null`

#### 4.6.4 通知

`resources/list_changed` 通知は **送出しない**。
カタログは起動時の設定で固定される (動的追加は今のところ未対応)。
将来 reload 機能を追加する際に通知 capability を追加する。

#### 4.6.5 キャッシュ可否と未知 URI の扱い

- **URI の集合 (`resources/list` の結果) は起動中は不変** で、クライアント
  側でセッション内キャッシュしてよい。
- **`resources/read` の返り値の `status` フィールドは時刻依存**
  (`last_sync_at`, `last_commit`, `last_outcome`, `last_error` が定期同期で
  更新される)。鮮度を必要とする用途では呼び出しのたびに再 read すること。
- `resources/read` の `id` / `branch` / `hosting` / `hosting_base_url` /
  `exclude_paths` / `description` / `refresh_interval_seconds` フィールドは
  起動中は不変。セッション内キャッシュ可能。
- **公開リソースに該当しない URI を `resources/read` した場合は MCP
  プロトコル層の error 応答** (`McpError`、メッセージ
  `"Unknown resource: <uri>"`) として返す。これはツール側エラー
  (§5.2 の `isError + JSON 文字列` 形式) とは別軸の応答であり、
  `{code,message,details}` 形式は適用されない。クライアントは
  `resources/list` で有効 URI を再取得すること。

## 5. エラー仕様

### 5.1 エラー応答形式

MCP プロトコルに従い、エラーは tool result の `isError: true`
フィールドと `content` 配下のテキストで表現する。

`content` のテキストは以下の JSON 形式の文字列とする:

```json
{
  "code": "REPO_NOT_FOUND",
  "message": "Repository 'main-app' is not configured",
  "details": {
    "repository": "main-app"
  }
}
```

### 5.2 エラーコード一覧

| コード | 意味 | 該当ツール | リカバリ可否 |
| --- | --- | --- | --- |
| `REPO_NOT_FOUND` | 指定リポジトリが設定にない | 全ツール | 不可 (設定変更が必要) |
| `REPO_NOT_READY` | リポジトリの初回 clone が未完了 | 全ツール | 可 (時間をおいて再試行) |
| `INVALID_PATH` | パストラバーサルや絶対パスを検出 | path/file_path を取る全ツール | 不可 (入力修正が必要) |
| `PATH_NOT_FOUND` | 指定パスがリポジトリ内に存在しない | path/file_path を取る全ツール | 不可 |
| `INVALID_PATTERN` | 検索/グロブパターンが不正 | search_code、list_files | 不可 |
| `FILE_TOO_LARGE` | ファイルサイズが上限超過 | read_file | 不可 (範囲指定では回避不能) |
| `FILE_BINARY` | テキストとして解釈できない | read_file | 不可 |
| `TIMEOUT` | ツール処理が制限時間を超過 | 全ツール | 可 (再試行・条件絞り込み) |
| `BACKEND_FAILURE` | ripgrep または git の異常終了 | 全ツール | 可 (一時的障害の可能性) |
| `INTERNAL_ERROR` | 上記に該当しないサーバー内部エラー | 全ツール | 可 (再試行) |

これらは **ツール呼び出し** (`tools/call`) のドメインエラーであり、
`isError: true` + content の JSON 文字列として返す。

`resources/read` で未知の URI を渡された場合のエラーは別軸 (MCP
プロトコル層の `McpError`)。§4.6.5 を参照。

### 5.3 エラーメッセージの規約

- `message` は英語、1 文、ピリオドなしで終わる
- `details` は JSON オブジェクトで、エラー固有の補助情報を含める
- 秘密情報 (認証トークン、SSH 鍵のパスなど) を含めてはならない
- スタックトレースを含めてはならない

### 5.4 入力バリデーションエラー

JSON Schema 違反 (型不一致、必須項目欠落、enum 範囲外、
最小値・最大値違反など) は MCP プロトコル層で
`-32602 Invalid params` として返却される。
ツール側のエラーコード体系は適用しない。

## 6. Git URL 生成仕様

検索結果およびファイル読み取り結果に付与する URL の生成規則。

### 6.1 ホスティング別フォーマット (単一行)

| ホスティング | URL 形式 |
| --- | --- |
| GitHub | `{base}/blob/{branch}/{path}#L{line}` |
| GitLab | `{base}/-/blob/{branch}/{path}#L{line}` |
| Bitbucket | `{base}/src/{branch}/{path}#lines-{line}` |
| Gitea | `{base}/src/branch/{branch}/{path}#L{line}` |

`{base}` はリポジトリのベース URL
(例: `https://github.com/example/main-app`)。
`{branch}` は設定で指定された参照ブランチ。
`{path}` は URL エンコード済みの相対パス。

### 6.2 範囲指定時のフォーマット

`read_file` および `search_code` で `context_before`/`context_after`
を指定した場合は、範囲アンカーを生成する。

| ホスティング | 範囲 URL 形式 |
| --- | --- |
| GitHub | `{base}/blob/{branch}/{path}#L{start}-L{end}` |
| GitLab | `{base}/-/blob/{branch}/{path}#L{start}-{end}` |
| Bitbucket | `{base}/src/{branch}/{path}#lines-{start}:{end}` |
| Gitea | `{base}/src/branch/{branch}/{path}#L{start}-L{end}` |

### 6.3 パスの URL エンコード

- 区切り文字 `/` はエンコードしない
- 空白は `%20` にエンコードする
- 非 ASCII 文字は UTF-8 → percent-encoding でエンコードする
- 既に予約されている文字 (`?`, `#`, `%`) はエンコードする

## 7. 設定ファイル仕様

### 7.1 repos.toml

リポジトリ定義の設定ファイル。配置場所は起動引数または
環境変数 `CODE_SEARCH_REPOS_PATH` で指定する。

```toml
[[repository]]
id = "main-app"
remote = "git@github.com:example/main-app.git"
branch = "main"
hosting = "github"
hosting_base_url = "https://github.com/example/main-app"
refresh_interval_seconds = 900
exclude_paths = ["docs/generated/", "vendor/"]
description = """\
Backend service for the main customer-facing app. FastAPI + SQLAlchemy.
Key dirs: billing/, auth/, models/.
"""
```

| フィールド | 必須 | 型 | 制約 |
| --- | --- | --- | --- |
| `id` | 必須 | string | `^[a-zA-Z0-9._-]+$`、サーバー内一意 |
| `remote` | 必須 | string | Git のリモート URL (SSH または HTTPS) |
| `branch` | 必須 | string | 参照するブランチ名 |
| `hosting` | 必須 | enum | `github`/`gitlab`/`bitbucket`/`gitea` |
| `hosting_base_url` | 必須 | string | Git URL 生成の基底 URL |
| `refresh_interval_seconds` | 任意 | integer | 60 以上。省略時は 900 |
| `exclude_paths` | 任意 | array | リポジトリルートからの相対パスのプレフィックス |
| `description` | 任意 | string | 8192 字以内。リポの中身を表す自由文 (AI 生成テキスト貼付想定)。LLM が複数リポから選ぶ際の主要な判断材料となる |

### 7.2 secrets.toml

認証情報を分離して格納する設定ファイル。
パーミッションは 600 とする。Git にコミットしてはならない。
配置場所は起動引数または環境変数 `CODE_SEARCH_SECRETS_PATH` で
指定する。

```toml
[secrets.main-app]
auth_type = "token"
token = "ghp_xxxxxxxxxxxxxxxxxxxx"

[secrets.internal-lib]
auth_type = "ssh_key"
ssh_key_path = "/etc/code-search/keys/internal-lib"
```

| フィールド | 必須 | 型 | 説明 |
| --- | --- | --- | --- |
| `auth_type` | 必須 | enum | `token`/`ssh_key`/`none` |
| `token` | 条件 | string | `auth_type=token` の場合に必須 |
| `ssh_key_path` | 条件 | string | `auth_type=ssh_key` の場合に必須 |

`[secrets.<id>]` の `<id>` は `repos.toml` の `id` と対応する。
`auth_type=none` の場合または該当セクションがない場合は
匿名アクセスとして扱う。

### 7.3 起動時の検証

サーバー起動時に以下を検証する。違反があれば起動を中止する。

- TOML のパースに成功すること
- 必須フィールドが全て揃っていること
- `id` がサーバー内で一意であること
- `hosting` が enum の範囲内であること
- 秘密情報ファイルのパーミッションが 600 以下であること

## 8. 性能保証

### 8.1 タイムアウト

各ツール呼び出しに対するサーバー側のタイムアウト。
これを超えた場合は `TIMEOUT` エラーを返す。

| ツール | タイムアウト |
| --- | --- |
| `search_code` | 10 秒 |
| `list_files` | 5 秒 |
| `list_tree` | 5 秒 |
| `read_file` | 3 秒 |

### 8.2 同時実行数

同一サーバーインスタンスで同時に処理するツール呼び出しの上限は
**16 件**とする。これを超える呼び出しは順次キューイングされる。

キューでの待機を含めた全体応答が 30 秒を超える場合は
`TIMEOUT` エラーを返す。

### 8.3 性能保証の前提

要件書 5.1 の性能要件 (search_code 95 パーセンタイル 2 秒以内など) は、
以下の前提下で保証する。

- リポジトリは要件書 6.4 の規模前提に収まる
  (1 リポジトリ 5 GB 以下、サーバー全体で 50 リポジトリ以下)
- サーバーホストは少なくとも 4 vCPU、8 GB RAM を備える
- ワークスペースは SSD 上に配置されている
- 同時実行数が上限 (16) に達していない

## 9. 互換性ポリシー

### 9.1 バージョニング

サーバーは Semantic Versioning 2.0.0 に従う。

- MAJOR: ツール削除、必須パラメータ追加、出力フィールドの削除など、
  クライアントの修正なしには動作しなくなる変更
- MINOR: ツール追加、任意パラメータ追加、出力フィールドの追加など、
  後方互換性のある変更
- PATCH: バグ修正、内部実装の変更

### 9.2 出力フィールドの追加

クライアントは未知の出力フィールドを無視できなければならない。
サーバーは MINOR バージョンアップで出力フィールドを追加できる。

### 9.3 設定ファイルスキーマ

設定ファイルの必須フィールド追加は MAJOR バージョンアップを伴う。
任意フィールド追加は MINOR で行う。

## 10. 参考文献

- [Model Context Protocol Specification](https://spec.modelcontextprotocol.io/)
- [JSON Schema](https://json-schema.org/)
- [Semantic Versioning 2.0.0](https://semver.org/)
- 本サーバーの要件書 (`requirements.md`)
