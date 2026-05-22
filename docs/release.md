# リリース手順

リリースはタグ push をトリガーに GitHub Actions が自動で作成する。
ワークフロー定義は
[`.github/workflows/release.yml`](../.github/workflows/release.yml)。

## 前提

- `pyproject.toml` の `version` を次のリリース番号に更新済み(SemVer)
- 変更が `main` にマージ済み
- `make verify` が通っている(CI でも検証される)

## 手順

1. **バージョンを更新する**
   `pyproject.toml` の `version` を次のリリース番号に変更し、PR を作成して
   `main` にマージする。

2. **タグを作成して push する**
   マージ後の `main` で:

   ```bash
   git fetch origin
   git checkout main
   git pull --ff-only
   git tag v0.0.0
   git push origin v0.0.0
   ```

3. **ワークフローの完了を待つ**
   GitHub Actions の `release` ワークフローが成功すると、GitHub Releases に
   以下が公開される:
   - リリースノート(コミットから自動生成: `--generate-notes`)
   - sdist (`*.tar.gz`) と wheel (`*.whl`)(`uv build` の成果物)

## タグの命名規約

- タグ名は **`v` プレフィックス + SemVer** に固定: `v0.0.0` / `v1.2.3`
- ワークフローのトリガーパターンは `v*.*.*`
- マッチしない例(起動しない): `0.0.0` / `release-0.0.0` / `0.0.0-rc1`

## 注意

- **GitHub UI から先に Release を作らない**
  タグ push がトリガー。UI で先に Release を作成するとワークフロー側で
  `release already exists` エラーになる。タグだけ push すれば良い。
- **タグの付け直しは避ける**
  誤ったコミットにタグを付けた場合は、新しいパッチバージョンで切り直す。
  既存タグの上書き push (`git push -f`) は GitHub Releases / 利用者の
  キャッシュとの整合が崩れるため禁止。
- **`pyproject.toml` の version とタグは一致させる**
  README のバージョンバッジは `pyproject.toml` から動的に取得するため、
  両者が食い違うと表示と Release タグが乖離する。

## リリース後

- README のバージョンバッジは `pyproject.toml` から動的に取得するため
  手動更新は不要(`main` に反映された時点で更新される)。
- 必要に応じて
  [`docs/tasks/task.md`](tasks/task.md) のタスク状態を更新する。
