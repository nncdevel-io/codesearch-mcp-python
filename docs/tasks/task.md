# TASKS

マイルストーン: M2（Python対応範囲を3.15まで拡大し依存ライブラリを更新）
ゴール: Python 3.11〜3.15の全版でmcp 2.xを含む最新依存のもと`make verify`が通る状態にする

## ワークフロールール

- タスク着手時にステータスを 🚧 に更新する
- 必要な検証をエージェント単独で完遂できた場合は ✅、人の確認が残る場合は 🧪 に更新し、未確認事項を明記する。判断がつかない場合は 🧪 に倒す
- 🧪 から ✅ への更新はユーザーのレビュー承認をもって行う
- DependsOn のタスクがすべて ✅ でないタスクには着手しない

## ステータス表記ルール

| Status | 意味 |
| ---- | ----- |
| ⏳ | 未着手、TODO |
| 🚧 | 作業中、IN_PROGRESS |
| 🧪 | 確認待ち、REVIEW |
| ✅ | 完了、DONE |
| 🚫 | 中止、CANCELLED |

## タスク一覧

| ID | Status | Summary | DependsOn |
| --- | --- | --- | --- |
| TASK-001 | 🧪 | CIのPythonマトリクスを3.11〜3.15に拡大する | - |
| TASK-002 | ✅ | mcp以外の依存ライブラリを最新版に上げuv.lockを更新する | - |
| TASK-003 | ✅ | mcpを2.xに上げサーバ構築(MCPServer化・prompts抑止・HTTP起動)とテストを移行する | TASK-002 |
| TASK-004 | ✅ | Resource登録(uri文字列化・MCPError)とそのテストをmcp 2.xへ移行する | TASK-003 |
| TASK-005 | ✅ | JSON-RPCデバッグログをmcp 2.xのstdio/HTTP両経路で出力できるよう再実装する | TASK-003 |
| TASK-006 | ✅ | scripts/probe.pyをmcp 2.xのクライアントAPIへ移行する | TASK-003 |
| TASK-007 | ✅ | spec/design/ADR/CLAUDE.mdのFastMCP・mcp 1.x記述を2.xに合わせて改訂する | TASK-004,TASK-005 |
| TASK-008 | ✅ | Python 3.11〜3.15の各版で`make verify`を実行し全版の合格を確認する | TASK-001,TASK-006,TASK-007 |
| TASK-010 | ✅ | 未知ツールの`tools/call`をMCP仕様どおり`-32602`のプロトコルエラーで返す | TASK-005 |
| TASK-011 | ✅ | spec.md §5.4の入力検証エラーをMCP仕様(ツール実行エラー)に合わせて改訂する | TASK-010 |
| TASK-009 | ✅ | CHANGELOGに対応Python範囲の拡大とmcp 2.x移行を記載する | TASK-008,TASK-011 |
| TASK-012 | ✅ | バージョンを0.2.0に上げ、READMEバッジとCHANGELOG見出しを揃える | TASK-009 |

## タスク詳細（補足が必要な場合のみ）

### TASK-001

- 注意: メイン版(3.13)、`requires-python >=3.11`、ruff/pyreflyの3.11ターゲットは変更しない

- 未確認: GitHub Actions上での3.14/3.15ジョブの実行結果
- 注意: 3.15ジョブはimport-linterのインストールと`make imports`を除外する(BACKLOG-001)

### TASK-003

- 注意: TASK-003〜TASK-005が揃うまで`make verify`は通らない。同一ブランチで連続して実施する

### TASK-005

- 補足: mcp 2.xではStreamable HTTPが`Server.run`を経由しないため、現行のフック方式は使えない

### TASK-007

- 注意: spec.mdの外部仕様(未知URI時のエラーなど)が変わる場合は改訂前にユーザー確認を取る

### TASK-008

- 補足: 3.15は`make imports`を除外して実行する。import-linterが依存するgrimp 3.17に3.15向けwheelがなく、ソースビルドにrustc 1.94以上が要るため

## Backlog一覧

| ID | Status | Summary | DependsOn |
| --- | --- | --- | --- |
| BACKLOG-001 | ⏳ | grimpの3.15向けwheel公開後にCIの3.15ジョブでimport検査を有効化する | TASK-001 |

## Backlog詳細（補足が必要な場合のみ）

### BACKLOG-001

- 補足: `.github/workflows/verify.yml`の`skip-imports`指定と条件分岐の手順を削除する
