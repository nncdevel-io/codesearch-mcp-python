# TASKS

マイルストーン: M1（Code Search MCP Server 完成 + ハーネス整備）
ゴール: Git管理ソースを検索するMCPサーバー（4ツール+Git同期+stdio/HTTP）を完成させ、AIエージェントが安全・再現可能に作業できるハーネス装備を整備する

## ワークフロールール

- タスク着手時にステータスを 🚧 に更新する
- タスク完了時にステータスを ✅ に更新する
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
| TASK-001 | ✅ | uvプロジェクト雛形とテスト/lint環境を構築する | - |
| TASK-002 | ✅ | ErrorCodeとToolError(エラーJSON生成)を実装する | TASK-001 |
| TASK-003 | ✅ | 相対パス検証(絶対/../拒否・正規化)を実装する | TASK-002 |
| TASK-004 | ✅ | ワークスペース封じ込めパス解決を実装する | TASK-003 |
| TASK-005 | ✅ | 4ホスティングの単一行Git URL生成を実装する | TASK-002 |
| TASK-006 | ✅ | Git URLの行範囲アンカー生成を実装する | TASK-005 |
| TASK-007 | ✅ | リポジトリ/秘密情報の設定Pydanticモデルを実装する | TASK-005 |
| TASK-008 | ✅ | 設定ローダと起動時検証(権限600含む)を実装する | TASK-007 |
| TASK-009 | ✅ | repos/secretsの設定例ファイルを作成する | TASK-008 |
| TASK-010 | ✅ | 結合テスト用bare gitリモートfixtureを用意する | TASK-001 |
| TASK-011 | ✅ | RepositoryManager(状態/パス/同期状況)を実装する | TASK-007,TASK-002 |
| TASK-012 | ✅ | git cloneによる初期取得と認証処理を実装する | TASK-011,TASK-010 |
| TASK-013 | ✅ | git fetch/reset更新とリポジトリ単位障害分離を実装する | TASK-012 |
| TASK-014 | ✅ | シェル非経由の非同期コマンドランナを実装する | TASK-002 |
| TASK-015 | ✅ | ripgrep検索/列挙のargv構築を実装する | TASK-001 |
| TASK-016 | ✅ | ripgrep --json出力のマッチ抽出を実装する | TASK-015 |
| TASK-017 | ✅ | 4ツール入力スキーマとToolContextを実装する | TASK-007 |
| TASK-018 | ✅ | read_fileの行番号整形とバイナリ判定を実装する | TASK-017 |
| TASK-019 | ✅ | read_fileツール本体を実装する | TASK-018,TASK-004,TASK-005,TASK-011 |
| TASK-020 | ✅ | search_codeツール本体を実装する | TASK-016,TASK-014,TASK-005,TASK-011 |
| TASK-021 | ✅ | list_filesツール本体を実装する | TASK-015,TASK-014,TASK-005,TASK-011 |
| TASK-022 | ✅ | list_treeのASCIIツリー整形を実装する | TASK-017 |
| TASK-023 | ✅ | list_treeツール本体(git ls-files連携)を実装する | TASK-022,TASK-014,TASK-011 |
| TASK-024 | ✅ | 検索系ツールにexclude_pathsフィルタを適用する | TASK-020,TASK-021,TASK-023 |
| TASK-025 | ✅ | ツール実行ガード(並列/タイムアウト/エラー)を実装する | TASK-002 |
| TASK-026 | ✅ | FastMCPサーバに4ツールを登録する | TASK-025,TASK-017,TASK-019,TASK-020,TASK-021,TASK-023,TASK-024 |
| TASK-027 | ✅ | 構造化ログと秘密情報の秘匿を実装する | TASK-001 |
| TASK-028 | ✅ | 最終同期状況の参照機能を実装する | TASK-011 |
| TASK-029 | ✅ | 任意のin-process定期同期スケジューラを実装する | TASK-013 |
| TASK-030 | ✅ | CLIのserve/syncサブコマンドを実装する | TASK-026,TASK-029,TASK-008 |
| TASK-031 | ✅ | stdioトランスポートの端点間テストを通す | TASK-030 |
| TASK-032 | ✅ | Streamable HTTPトランスポートの端点間テストを通す | TASK-030 |
| TASK-033 | ✅ | READMEと運用手順(同期/起動/環境変数)を整備する | TASK-030 |
| TASK-034 | ✅ | 性能スモークと仕様適合チェックを実施する | TASK-031,TASK-032,TASK-033 |
| TASK-035 | ✅ | uv.lockをgitignoreから外して依存を完全固定する | TASK-001 |
| TASK-036 | ✅ | Ruffにformat checkとSルール(bandit相当)を追加する | TASK-001 |
| TASK-037 | ✅ | Pyreflyによるstrict型検査を導入する | TASK-001 |
| TASK-038 | ✅ | import-linterで層間依存契約を宣言する | TASK-001 |
| TASK-039 | ✅ | pytestのカバレッジ計測と閾値を導入する | TASK-001 |
| TASK-040 | ✅ | pip-auditを依存脆弱性チェックとして導入する | TASK-035 |
| TASK-041 | ✅ | SPEC.mdのJSON Schemaと実装Pydanticモデルの整合性テストを追加する | TASK-017 |
| TASK-042 | ✅ | Makefileで`make verify`集約コマンドを定義する | TASK-036,TASK-037,TASK-038,TASK-039,TASK-040 |
| TASK-043 | ✅ | GitHub Actions CIで`make verify`を強制する | TASK-042 |
| TASK-044 | ✅ | devcontainer(Python+uv+git+ripgrep+make)を整備する | TASK-035 |
| TASK-045 | ✅ | .claude/settings.jsonでプロジェクト固有の許可/禁止を整備する | TASK-001 |
| TASK-046 | ✅ | CLAUDE.mdにハーネス規約(subprocess安全/uv強制/型注釈/import副作用禁止/`make verify`)を追記する | TASK-042 |
| TASK-047 | ✅ | READMEを利用者向けに再構成し、インストール/運用の記述を分離する | TASK-033 |
| TASK-048 | ✅ | docs/installation.mdを作成して前提・uv sync・devcontainer導入手順を集約する | TASK-047 |
| TASK-049 | ✅ | docs/operations.mdを作成して常設運用・同期トリガ・監視を集約する | TASK-047 |
| TASK-050 | ✅ | READMEにMCPクライアント側の接続設定例(stdio/HTTP)を追加する | TASK-047 |
| TASK-051 | ✅ | READMEにバッジ(CI/Python/ライセンス/Ruff/uv/MCP)を追加する | TASK-047 |
| TASK-052 | ✅ | CIにpaths-ignoreを追加しドキュメント単独変更ではverifyを走らせない(spec/は対象維持) | TASK-043 |
| TASK-053 | 🚫 | CIにPython 3.11/3.12/3.13のマトリクスを追加する | TASK-043 |
| TASK-054 | ✅ | CIのPythonマトリクスを撤回しメイン版(3.13)に固定する。ruff/pyreflyは3.11ターゲットで最低保証を担保 | TASK-053 |
| TASK-055 | ✅ | cspellの設定を追加し`make spell`/CIから実行できるようにする | TASK-042,TASK-043 |
| TASK-056 | ✅ | CIのみPython 3.11/3.12/3.13マトリクスで検証する。ローカル/devcontainerはメイン版(3.13)固定 | TASK-054 |
| TASK-057 | ✅ | 配布方針を `docs/distribution.md` に明文化する(主=Container、副=Source、PyPIは採用しない) | TASK-049 |
| TASK-058 | ✅ | Dockerfile(multi-stage、git+ripgrep同梱、非rootユーザ)とdocker-composeサンプルを追加する | TASK-057 |
| TASK-059 | 🚫 | GHCRへのイメージpushをGHA(タグ駆動v*)で自動化する (利用者判断により実施不要) | TASK-058 |
| TASK-060 | 🚫 | READMEのMCPクライアント設定例にCursorを追加する (利用者判断によりキャンセル: 既存例から類推可能) | TASK-050 |
| TASK-061 | ✅ | `scripts/probe.py` 参照クライアントを追加しREADMEに動作確認手順を載せる | TASK-058 |
| TASK-062 | ✅ | `docs/operations.md` にHTTP認証パターン例(リバプロBearer/mTLS)を追記する | TASK-049 |
| TASK-063 | ✅ | LLM向け使い分けガイダンスを `docs/usage-for-llm.md` に新設しFastMCP(instructions=…)/各tool descriptionに反映する | TASK-026 |
| TASK-064 | ✅ | `tests/test_tool_descriptions.py` でinstructions/descriptionのキーフレーズ存在を回帰防止する | TASK-063 |
| TASK-066 | ✅ | 各ツールにOutputModelを定義しFastMCPにoutputSchemaを広告させる(エラー時のCallToolResult経路は維持) | TASK-026 |
| TASK-067 | ✅ | Resourcesにリポジトリカタログを実装する(URI `codesearch://repo/{id}`、MCPの`resources/list`と`resources/read`両ハンドラを実装)。promptsは引き続き非公開 | TASK-026 |
| TASK-068 | ✅ | serverInfoのname/versionを本プロジェクト値(`codesearch-mcp`/`__version__`)に修正する | TASK-026 |
| TASK-069 | ✅ | spec.md §2.2を「toolsとresourcesを公開する」に改訂、§3にリポジトリResourceのURI/Schemaを追記 | TASK-067 |
| TASK-071 | ✅ | FastMCPのpromptsハンドラを抑止しcapabilities.promptsを広告しないようにする(spec §2.2整合) | TASK-026 |
| TASK-072 | ✅ | `list_repositories`ツール(5つ目)を追加しResources非対応ホストでもカタログをLLMに届ける。spec/requirements/CLAUDE.mdの「4ツール」記述も更新 | TASK-067 |
| TASK-073 | ✅ | spec.mdに未知URI挙動(McpError)と`resources/read`のキャッシュ注意を追記 | TASK-069 |
| TASK-074 | ✅ | distribution.mdにバージョンbump手順とCHANGELOG運用を追記 | TASK-057 |
| TASK-075 | ✅ | `RepositoryConfig` に任意の `description` フィールド (自由文、AI生成テキスト貼付想定) を追加 | TASK-072 |
| TASK-076 | ✅ | `description` を Resource description と `list_repositories` の各エントリに伝搬。spec / テストも更新 | TASK-075 |
| TASK-077 | ✅ | requirements §6.4 と operations.md に「実運用は数リポが現実的、超過時はMCPサーバ分割」を明記、examples/repos.toml に description 入り例 | TASK-076 |
| TASK-078 | ✅ | examples/repos.tomlのremote例をHTTPSとSSHの両方が見えるよう1件ずつに整える | TASK-077 |
| TASK-070 | ✅ | tool descriptionに「repositoryの有効値はresources/listから取得できる」旨を追記、llm_guidance/usage-for-llmに反映 | TASK-067 |

## タスク詳細（補足が必要な場合のみ）

### TASK-008

- 補足: 検証は TOMLパース・必須項目・id一意・hosting enum・秘密ファイル権限600
- 注意: 違反時は起動を中止する

### TASK-012

- 補足: 認証は token / ssh_key / none に対応する
- 注意: 参照ブランチのみの単一ブランチ取得とする

### TASK-013

- 注意: 個別リポジトリの取得失敗を他リポジトリへ波及させない

### TASK-019

- 注意: サイズ超過は FILE_TOO_LARGE、バイナリは FILE_BINARY を返す

### TASK-020

- 補足: 出力モードは content / files_with_matches / count
- 注意: max_results 超過時は truncated を立てる

### TASK-023

- 注意: git追跡ファイルのみ対象（未追跡・.gitignore対象は除外）

### TASK-024

- 補足: exclude_paths はリポジトリ設定のプレフィックス一致で除外

### TASK-026

- 補足: 公開ツールは search_code / list_files / list_tree / read_file の4つに限定
- 注意: FastMCP/MCP の API 名は公式ドキュメントで確認して合わせる

### TASK-029

- 補足: 既定は無効、設定で有効化する
- 注意: リクエスト処理をブロックしない

### TASK-030

- 補足: serve は --transport stdio|http を選択、同期はリクエストパスから分離
- 注意: serve の起動 API 名は公式ドキュメントで確認して合わせる

### TASK-034

- 注意: 規模前提（1リポジトリ5GB以下/50リポジトリ以下）下で search_code 2秒未満

## Backlog一覧

| ID | Status | Summary | DependsOn |
| --- | --- | --- | --- |
| BACKLOG-001 | ⏳ | リクエスト時のstaleness判定で非ブロッキング更新を実装する | - |

## Backlog詳細（補足が必要な場合のみ）

### BACKLOG-001

- 補足: 設計上の任意機能。要件の定期更新はCLIとスケジューラで充足済み
- 注意: 応答をブロックせず応答後にバックグラウンド更新する
