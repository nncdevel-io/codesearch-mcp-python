# 配布方針

本サーバの配布形態と、その選定理由を明示する。利用者が「どの方法で
入れて、どこからクライアントを繋ぐか」を判断するための文書。

## 結論

| 区分 | 形態 | 想定利用者 |
| --- | --- | --- |
| **主** | **コンテナイメージ (GHCR)** — Streamable HTTP で常駐 | 組織や個人がサーバとして常設し、複数の MCP クライアントから利用 |
| **副** | **ソース配布 (git clone + uv sync)** | コントリビュータ / 個人開発者がローカルで動かす場合 |
| 不採用 | PyPI / uvx | — (理由は後述) |

クライアント (Claude Code / Claude Desktop / Cursor / 自前チャット
アプリ等) は本プロジェクトでは作らず、サードパーティ既製品を使う。
各クライアントへの接続設定の雛形は README に掲載する。

## なぜコンテナを主にするか

このサーバはステートフル・常駐型のため、stdio + uvx 起動モデル
(典型的なステートレス MCP サーバの配布形態) と噛み合わない。具体的に:

- **永続ワークスペースを持つ** (1 リポジトリあたり最大 5 GB × 50
  リポジトリ規模を想定。要件 6.4)
- **定期 Git 同期が前提** (要件 4.5、`codesearch-sync` CLI または
  in-process スケジューラ)
- **複数リポジトリのカタログを共有** する設計
  (`repos.toml` は組織横断で記述する想定)
- 設計 §2 で **「Git 同期はリクエストパスから完全分離・デプロイ非依存」**
  と明言、`--transport http` を一級市民として扱う

各利用者が `uvx codesearch-mcp` で個別起動すると、全ユーザが全リポ
ジトリを自分のマシンに clone することになり、規模前提・性能要件と
噛み合わない。

コンテナ運用なら:

- ワークスペースはボリュームに永続化
- 同期スケジューラは同居 or 別 CronJob で集約
- 複数利用者は同じ HTTP エンドポイントを共有
- 認証はリバースプロキシ層に集約 (`docs/operations.md` 参照)

## なぜソース配布も残すか

- コントリビュータの開発体験のため (`uv sync --frozen` で開発環境構築)
- 1 利用者・1 マシン・自分のリポだけ叩く個人開発ケース
- devcontainer / IDE インテグレーションのため

ソース配布の手順は `docs/installation.md` に集約する。

## なぜ PyPI / uvx を採用しないか

| 観点 | PyPI/uvx モデル | 本サーバ |
| --- | --- | --- |
| 状態保持 | ステートレス前提 | 数百 GB のワークスペース |
| 起動形態 | クライアントが都度 subprocess を起動 | 常駐 (定期同期スケジューラ含む) |
| ユーザ単位 | ユーザごとに独立 | 組織で 1 つの同期済みカタログを共有 |
| 認証 | 局所 (stdio 経由) | HTTP 経路で集約 |

PyPI 公開を後付けで足すことは可能だが、それを「補助的な配布」として
推奨する意味はない (ユーザが期待する `uvx` 体験 = "都度ダウンロードして
すぐ使い捨て" と、本サーバの設計が逆向き)。誤誘導になるため不採用とする。

## クライアントの方針

(2025-05 時点)

| 層 | 提供元 | 本プロジェクトの仕事 |
| --- | --- | --- |
| MCP ホストアプリ (Claude Code / Claude Desktop / Cursor / 自前) | サードパーティ | 作らない・公開しない |
| クライアント側設定 (`mcpServers` JSON / 接続例) | 本プロジェクト | README に Claude Code / Claude Desktop / Python SDK の 3 例 (他クライアントは利用者側で類推) |
| 参照クライアント (動作確認用) | 本プロジェクト | `scripts/probe.py` を同梱 (MCP ホスト無しで生存確認可能) |
| 型付クライアント SDK パッケージ | — | 不採用 (公式 `mcp` SDK で十分) |

## バージョン管理とリリース

### バージョニング規約

[Semantic Versioning 2.0.0](https://semver.org/) に従う。判定基準は
仕様書 §9 と整合:

| 種別 | 該当変更 | 例 |
| --- | --- | --- |
| **MAJOR** | クライアント修正なしには動作しなくなる変更 | 公開ツール削除、必須パラメータ追加、出力フィールドの削除・型変更、エラーコード意味変更、公開 capability の削除 |
| **MINOR** | 後方互換のある追加 | 新ツール追加、任意パラメータ追加、出力フィールド追加、新エラーコード追加、`description` 等の運用フィールド追加 |
| **PATCH** | バグ修正・内部実装変更 | リネーム前のフィールドを維持しつつ実装を入れ替え、ログ出力の調整、性能改善、依存更新 |

判断に迷ったときは、**クライアント (= MCP ホスト + LLM) 視点で
"対応コードに手を入れずに動くか"** で切る。動かないなら MAJOR。

### 単一の真実: `src/codesearch_mcp/__init__.py`

バージョン値は `__version__` に 1 か所だけ書く。FastMCP の
`serverInfo.version` (`initialize` 応答) と `pyproject.toml` の
`project.version` は同じ値を保つ。

`pyproject.toml` 側は **hatch の動的バージョン** を使い、`__init__.py`
を読みに行く設定にしているため、二重管理は発生しない (将来の改善:
現状は `pyproject.toml` の `version = "0.1.0"` がハードコードされて
いるので、`[tool.hatch.version]` で `path = "src/codesearch_mcp/__init__.py"`
を指す動的バージョンに切り替える)。

### 手順

新リリースを切る運用フロー (人手):

1. **変更を確認**
   `git log --oneline v<前回のタグ>..HEAD` で差分を眺め、上の表で
   MAJOR / MINOR / PATCH のどれかを決める。
2. **`__init__.py` の `__version__` を更新**
   例: `0.1.0` → `0.2.0`
3. **`CHANGELOG.md` に新エントリを追加** (詳細は次節)
4. **コミット** `chore: release v0.2.0`
5. **タグを打つ** `git tag -a v0.2.0 -m "..."`
6. **push** `git push && git push --tags`

これ以降のコンテナ配布は外部運用 (今のところ GHA での自動 push は未採用、
利用者が必要なら `docker build` をローカルで実行)。

### CHANGELOG.md

[Keep a Changelog 1.1.0](https://keepachangelog.com/) フォーマットを採用。
仕様書 §9 の互換性ポリシーを利用者が追えるよう、**MCP の公開面
(ツール / Resources / 設定スキーマ / エラーコード / capability) に
関係する変更は必ず記録** する。内部リファクタは省略可。

リポジトリルートに `CHANGELOG.md` を置き、以下の骨格を保つ:

```markdown
# Changelog

All notable user-facing changes to this MCP server.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- ...

### Changed
- ...

### Removed / Deprecated / Fixed / Security
- ...

## [0.2.0] - 2026-XX-XX

### Added
- ...
```

リリース時は `[Unreleased]` を `[<version>] - <date>` に格下げ、
直下に新しい `[Unreleased]` を作って引き継ぐ。

カテゴリ:

- **Added** — 新ツール、新 Resource、任意パラメータ、新エラーコード等の追加
- **Changed** — 既存挙動の変更 (後方互換)
- **Deprecated** — 次回 MAJOR で削除予定の機能
- **Removed** — 削除した機能 (MAJOR でのみ発生)
- **Fixed** — バグ修正
- **Security** — 脆弱性関連修正

## 関連文書

- 導入手順 (ソース / コンテナ): [`installation.md`](installation.md)
- 常設運用 (Compose / K8s / 同期戦略): [`operations.md`](operations.md)
- 仕様: [`spec/spec.md`](spec/spec.md)
