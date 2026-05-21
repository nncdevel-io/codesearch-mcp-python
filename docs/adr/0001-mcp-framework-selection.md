# ADR-0001: MCP フレームワーク選定 — 公式 `mcp` Python SDK

## ステータス

Accepted

- 当初決定: 2026-05-19 (`docs/design/design.md` §1 表に確定済み)
- 本 ADR としての記録: 2026-05-21 (遡及記録、PYSEC-2025-183 対応に伴い
  選定理由を明文化)

## 結論サマリ

| 選択肢 | MCP 仕様追随 | stdio / HTTP 両対応 | `pyjwt` が依存に入るか | 追加で増える依存 | 実装・保守コスト | 結論 |
| --- | --- | --- | --- | --- | --- | --- |
| **A. 公式 `mcp` SDK (FastMCP 同梱)** | SDK が自動追随 | 標準サポート | はい (必須依存) | なし | 最小 | **採用** |
| B. FastMCP 3.x (jlowin/Prefect) | 内部で公式 SDK を呼ぶ | 標準サポート | はい (公式 SDK 経由) | `authlib` ほか増加 | 中 (移行コスト + 追加層の学習) | 不採用 — A の上位互換にならず依存が増えるだけ |
| C. 自前 JSON-RPC + MCP 実装 | 当方で追随し続ける必要 | 全て自前 | 入れない選択も可 | プロトコル実装一式 | 大 (継続的) | 不採用 — 費用対効果が成立しない |

**決定の核**: B を採っても内部で公式 `mcp` SDK を経由するため
`pyjwt` 依存は逃れられない (むしろ `authlib` 等で増える)。C は MCP
プロトコル追随を恒久的に当方が負うため、本プロジェクトのスコープに
見合わない。A が信頼性・正確性・効率いずれでも他に勝る唯一の妥当解。

## 文脈

本プロジェクトは Model Context Protocol (MCP) サーバを Python で
実装する。要件・仕様上、フレームワーク選定に効く制約は次の通り。

- **MCP 仕様準拠**: Tools / Resources / Prompts のスキーマ、エラー
  コード、トランスポートが MCP プロトコル仕様に追随し続ける必要が
  ある (`docs/spec/spec.md` §1, §6)。
- **2 トランスポート両対応**: `stdio` と Streamable HTTP の両方を
  サポートする (`docs/requirements.md` 4.4)。
- **非同期実行が前提**: 検索は外部コマンド (`ripgrep`, `git`) の
  サブプロセスを並列に走らせる。フレームワークは `asyncio` ベース
  であることが望ましい (`docs/design/design.md` §1)。
- **保守性**: MCP 仕様は現在もアクティブに更新されている。プロトコル
  追随コストを当方が負わない方が長期保守上有利。
- **依存ツリーの健全性**: `make verify` の `pip-audit` ゲートを
  通せること。サプライチェーン上、公式・大規模利用されている層を
  選択肢として優先する。

## 検討した選択肢

### A. 公式 `mcp` Python SDK (modelcontextprotocol/python-sdk)

- 提供元: Anthropic (MCP 仕様の策定元)
- 高レベル API である FastMCP 1.0 が 2024 年に取り込まれ、`mcp.server.fastmcp`
  として同梱。
- 必須依存: `anyio`, `httpx`, `jsonschema`, `pydantic`, `pydantic-settings`,
  `pyjwt[crypto]`, `python-multipart`, `sse-starlette`, `starlette`,
  `uvicorn` ほか。`pyjwt` は MCP の OAuth 2.1 ベース認可フロー
  (RFC 7523 `private_key_jwt`) の SDK 側実装で必須化されている。
- ライセンス: MIT。

### B. FastMCP 3.x (jlowin/fastmcp, Prefect メンテナンス)

- FastMCP 1.0 が公式 SDK に取り込まれた後も、独立した上位フレーム
  ワークとして 3.x 系列で活発に開発が継続している (2026-05 時点で
  v3.3.1)。
- 自称「MCP サーバ全言語の約 70% を支える standard framework」。
- **構造上の依存**: `fastmcp-slim` 経由で公式 `mcp>=1.24.0,<2.0` を
  内部利用する。すなわち FastMCP 3.x を採用しても **公式 `mcp` SDK
  は依存ツリーに必ず入り、`pyjwt` も同じく入る**。
- さらに `authlib` (別の OAuth 実装) を `client` / `server` extras
  経由で要求するため、現状より依存総量が増える。
- ライセンス: Apache-2.0。

### C. 自前で JSON-RPC + MCP プロトコルを実装

- フレームワーク非依存にし、`mcp` パッケージを依存から外す。
- プロトコル仕様の追随、Tools / Resources / Prompts のスキーマ整合、
  3 種類のトランスポート (stdio / Streamable HTTP / SSE) のロード
  バランシング、互換性試験までを当プロジェクトで負う。

## 決定

**A. 公式 `mcp` Python SDK (FastMCP 同梱) を採用する。**

選定一行: 信頼性 (仕様策定元配布) / 正確性 (仕様準拠が担保) /
効率 (即時に MCP 仕様の全機能を使える) のいずれでも A が優位、
他に妥当解なし。

### 理由

1. **仕様追随コストを SDK 側に委譲できる**。MCP 仕様は今後も
   進化する。Anthropic 配布の SDK を採用すれば、仕様変更追随は
   SDK アップグレードに帰着する。
2. **B (FastMCP 3.x) でも `mcp` SDK と `pyjwt` は結局入る**。
   B は公式 SDK のラッパであり、依存上の "脱出経路" にならない。
   むしろ `authlib` 等が追加で乗る分、攻撃面と保守コストが増える。
   B が提供する付加価値 (デコレータ群、追加のクライアント機能等)
   は本プロジェクトの要件には不要。
3. **C (自前実装) は費用対効果が成立しない**。MCP のトランスポート
   3 種対応、スキーマ整合、エラーモデル互換、ホスト LLM 側
   実装との相互運用試験までを内製するのは、本プロジェクトのスコープ
   (Git 管理ソースコード検索) から大きく逸脱する。
4. **A は同期的 Python 標準ライブラリと整合**する。FastMCP は
   `asyncio` ベースで、本プロジェクトの「全体 async / 外部コマンド
   は `asyncio.create_subprocess_exec`」方針 (design §1) と一致。

## 帰結

### メリット

- MCP プロトコル仕様への自動追随。
- stdio / Streamable HTTP 両トランスポートが SDK 標準でサポート。
- ホスト (Claude Desktop / VS Code MCP / その他) との相互運用が
  Anthropic 公式テストパスを通った範囲で保証される。
- 検証・テストの焦点を MCP プロトコル層ではなく、本プロジェクト
  固有のロジック (検索バックエンド、パス安全性、リポジトリ管理) に
  集中できる。

### デメリット / 受容したトレードオフ

- **依存ツリーが大きい** (約 67 packages)。これは MCP プロトコル
  仕様 (OAuth 2.1、JSON Schema、SSE、ASGI) を完全に満たすコストで
  あり、A / B いずれを採っても同等。
- **SDK のバージョン方針に従う必要がある**。`mcp` の breaking
  change はこちらが追随する。MCP 仕様が安定するまでは継続コスト
  として受容。
- **`pyjwt[crypto]` が必須依存として常に入る**。当方コードからは
  `mcp.client.auth.*` を import していないため実行時には未使用だが、
  仮想環境にはインストールされる。これは下記「関連する運用上の
  対処」の対象。

### 影響範囲

- 実装: `src/codesearch_mcp/server.py` が FastMCP に直接依存。
  低レベル API (`mcp.server.Server`) には触れない方針。
- テスト: `tests/test_server_*.py` は FastMCP の `Context` と
  `tool` デコレータ前提でテストを記述。
- 配布: `pyproject.toml` の `[project.dependencies]` で
  `mcp[cli]>=…` を直接ピン留めする (B のような中間ラッパを
  挟まない)。

## 関連する運用上の対処 — PYSEC-2025-183 (pyjwt)

本決定の **副作用** として、`mcp` SDK が必須依存する `pyjwt[crypto]`
について、CI の `pip-audit` ゲートで PYSEC-2025-183 (CVE-2025-45768)
が検出される事象がある。

### 経緯

- 2026-05-21 の CI で `make audit` が落ちた
  ([Actions run 26220177150](https://github.com/nncdevel-io/codesearch-mcp-python/actions/runs/26220177150))。
- 対象は `pyjwt 2.12.1` (`mcp 1.27.1` の必須依存として導入)。
- `pip-audit` の `Fix Versions` カラムが空。

### 評価

- **PyJWT メンテナーが disputed として公式に否認**。鍵長の妥当性
  検証はライブラリではなくアプリケーションの責務、という立場。
  ([OSV PYSEC-2025-183](https://osv.dev/vulnerability/PYSEC-2025-183))
- そのため上流に修正版が存在しない (最新の `pyjwt 2.12.1` でも検出
  され続ける)。
- 本プロジェクトは MCP **サーバ**実装であり、`pyjwt` を使うのは
  `mcp.client.auth.extensions.client_credentials` の OAuth 2.1
  `private_key_jwt` クライアント認証フローのみ。当方コードから
  この経路は一切 import されない (`make imports` の import-linter
  契約でも `mcp.client.*` への依存は存在しないことを確認可能)。
- フレームワーク選定 (本 ADR の決定) を見直しても、選択肢 B でも
  `pyjwt` は同じく入るため、SDK 乗り換えでは解決しない。

### 採用した対処

`Makefile` の `audit` ターゲットで当該 CVE ID をピンポイント除外
する (`pip-audit --ignore-vuln PYSEC-2025-183`)。理由は同ターゲット
内コメントに明記する。

```make
audit: ## pip-audit dependency vulnerability scan
        # PYSEC-2025-183 (CVE-2025-45768): disputed by PyJWT maintainers — key length
        # is the application's responsibility, no upstream fix exists, and pyjwt is
        # a transitive dep via mcp (not used directly by this project).
        $(UV) run pip-audit --skip-editable --ignore-vuln PYSEC-2025-183
```

### レビュー条件 (この `--ignore-vuln` を外す契機)

以下のいずれかが発生した場合、`Makefile` の除外指定を取り除いて
再評価すること。

1. PyJWT 上流に修正版がリリースされた (`pip-audit` の `Fix Versions`
   カラムに具体的なバージョンが入る)。
2. OSV / NVD で当該 CVE が Withdrawn / Rejected に変更された。
3. MCP プロトコル仕様から OAuth 2.1 認可要件が外れ、`mcp` SDK の
   必須依存から `pyjwt` が外れた。
4. 本プロジェクトが `mcp.client.auth.*` を直接利用する設計に移行
   した (この場合は ignore 維持の正当性が失われるため、別途
   設計判断が必要)。

### 範囲外であることの明示

この `--ignore-vuln` は **PYSEC-2025-183 のみ** を抑制する。`pyjwt`
パッケージ全体を監査対象外にしているわけではないため、今後 `pyjwt`
に新たな CVE が報告された場合は通常通り `pip-audit` で検出され、
CI が落ちる。

## 参考

- MCP 仕様: <https://modelcontextprotocol.io>
- 公式 Python SDK: <https://github.com/modelcontextprotocol/python-sdk>
- FastMCP 3.x: <https://github.com/jlowin/fastmcp>
- PYSEC-2025-183: <https://osv.dev/vulnerability/PYSEC-2025-183>
- RFC 7523 (OAuth 2.0 JWT Profile for Client Authentication):
  <https://datatracker.ietf.org/doc/html/rfc7523>
