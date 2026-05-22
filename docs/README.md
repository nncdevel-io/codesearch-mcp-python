# docs

本リポジトリのドキュメント。読み手別に分類している。
利用者向けの主要文書は
[ルートの `README.md`](../README.md#-ドキュメント) からも辿れる。

## 利用者・運用者向け

- [installation.md](installation.md) — 導入・初期設定
- [operations.md](operations.md) — 常設運用・同期戦略・監視
- [distribution.md](distribution.md) — 配布方針
  (どの形態で入れてどこから繋ぐか)
- [spec/spec.md](spec/spec.md) — 外部仕様
  (MCP ツール入出力 / エラー / 設定ファイル / 性能保証)
- [usage-for-llm.md](usage-for-llm.md) — LLM 向け利用ガイダンス
  (MCP capability discovery 文言の原本)
- [agent-sequence.md](agent-sequence.md) — エージェント連携シーケンス
  (`spec/spec.md` / `usage-for-llm.md` を読むときの補助線)

## 開発者・メンテナ向け

- [requirements.md](requirements.md) — 要件 (スコープ / 機能・非機能要件)
- [design/design.md](design/design.md) — 内部設計 (アーキテクチャと
  ロック済み決定事項)
- [release.md](release.md) — リリース手順 (タグ push で GitHub Actions が
  自動公開)
- [tasks/task.md](tasks/task.md) — 実行計画 (WBS タスク一覧)

### Architecture Decision Records

- [adr/0001-mcp-framework-selection.md](adr/0001-mcp-framework-selection.md)
  — MCP フレームワーク選定 (公式 `mcp` Python SDK)

## ドキュメント階層

要件 → 仕様 → 設計 → 実行計画 は厳密な階層関係にあり、上流ドキュメントに
反する記述を下流に書いてはならない。

1. [requirements.md](requirements.md) — 何を解くか
2. [spec/spec.md](spec/spec.md) — 外部からどう見えるか
3. [design/design.md](design/design.md) — 内部でどう実現するか
4. [tasks/task.md](tasks/task.md) — どの順で作るか
