# 運用

複数人や常設デプロイで `codesearch-mcp` を運用する場合の手引き。
個人利用 (ローカルで MCP クライアントから呼ぶ) の場合は README と
`docs/installation.md` で足りる。

## 同期トリガの選択

Git 同期 (取得 / `fetch + reset --hard`) はリクエストパスから完全に
分離されている (`docs/design/design.md` §2)。同期トリガは 3 系統あり、
**いずれかを選ぶ** か **複数併用** する。

| トリガ | 適している場面 | 起動方法 |
| --- | --- | --- |
| ワンショット CLI | cron / systemd timer / Kubernetes CronJob / CI から駆動 | `codesearch-sync` |
| in-process スケジューラ | 常駐プロセスで完結させたい (cron が無い環境) | `codesearch-mcp serve --enable-scheduler` |
| 手動 | 開発時 / オンデマンド | `codesearch-sync --repository <id>` |

リクエスト時の git pull は仕様上禁止される (要件書 5.1 の p95 2 秒を
侵害する)。

### cron 例

15 分ごとに全リポジトリを同期する設定の例:

```cron
*/15 * * * * /usr/local/bin/uv run --directory /opt/codesearch-mcp \
    codesearch-sync \
        --repos /etc/codesearch/repos.toml \
        --secrets /etc/codesearch/secrets.toml \
        --workspace-root /var/lib/codesearch/workspaces
```

`codesearch-sync` は失敗があれば終了コード 1 を返すので、cron の MAILTO や
監視システムから検知できる。

### systemd timer 例

```ini
# /etc/systemd/system/codesearch-sync.service
[Unit]
Description=codesearch-mcp git sync (one-shot)

[Service]
Type=oneshot
User=codesearch
ExecStart=/usr/local/bin/uv run --directory /opt/codesearch-mcp \
    codesearch-sync --repos /etc/codesearch/repos.toml \
                    --secrets /etc/codesearch/secrets.toml \
                    --workspace-root /var/lib/codesearch/workspaces

# /etc/systemd/system/codesearch-sync.timer
[Unit]
Description=Run codesearch-sync every 15 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
```

### in-process スケジューラ

```bash
uv run codesearch-mcp serve --transport http \
    --enable-scheduler \
    --repos /etc/codesearch/repos.toml \
    --secrets /etc/codesearch/secrets.toml \
    --workspace-root /var/lib/codesearch/workspaces
```

`refresh_interval_seconds` (リポジトリごと、既定 900 秒) ごとに非同期で
`fetch + reset --hard` を行う。リクエスト処理はブロックしない。

## 同期状況の確認

```bash
uv run codesearch-mcp status --repos /etc/codesearch/repos.toml
```

各リポジトリの `state` (`ready` / `failed` / `uninitialized`)、
`last_outcome`、`last_sync_at`、`last_commit`、`last_error` を JSON で返す。
監視システムから定期収集する用途を想定している。

## 障害分離

- 個別リポジトリの clone / fetch 失敗は他リポジトリに波及しない。
  既に同期成功実績があるリポジトリは `state=ready` を保持し、
  検索ツールから引き続き利用可能。
- 初回 clone 前の状態で検索が呼ばれた場合は `REPO_NOT_READY` を返す。
  リトライ可能。

## ログ

構造化 JSON ログを stderr に出力する。`CODE_SEARCH_LOG_LEVEL` で
`DEBUG` / `INFO` / `WARNING` / `ERROR` を切り替える。

秘密情報 (URL に埋め込まれたトークン、`token=` パラメータなど) は
`codesearch_mcp.logging.redact()` で自動的に `***` に置換される。

## リポジトリ description の運用 (運用側の観点)

`repos.toml` の `description` フィールドの **書き方ガイドライン** は
[`installation.md`「リポジトリ description の設計」節](installation.md)
を参照。本節は運用側 (起動・監視) の事項のみ記す。

### 起動時の WARNING

`description` が未設定のリポが **2 件以上** ある場合、起動時に
`config_warning` イベントを WARNING レベルで出力する。起動は中断しない。
監視 / アラート設定でこれを検知し、`repos.toml` に description を追記する。

### 規模上限との関係

[要件書 §6.4.1](../requirements.md) にあるとおり、MCP クライアント側で
LLM に渡せる文脈枠は限られている。description は LLM 文脈に乗るため、
リポ数 × description 長 が線形にトークンを食う。

**実運用は 5〜10 リポ程度が現実的** で、それ以上はチーム / ドメイン単位で
MCP サーバインスタンスを分割する。50 リポ × 各 200 文字で約 10K 文字
に達する点に注意。

## 規模前提と性能

要件書 6.4 / 仕様書 8.3 に従う:

- 1 サーバインスタンスあたり 50 リポジトリまで
- 1 リポジトリあたり 5 GB まで
- 4 vCPU / 8 GB RAM / SSD を想定

これを超える場合は複数インスタンスに分割する。1 インスタンスあたりの
同時実行ツール呼び出しは 16 件まで、キュー含めた応答 30 秒で `TIMEOUT`。

## トランスポートと公開範囲

- **stdio** は同一マシンの単一クライアントに対する公開を想定。
- **Streamable HTTP** で他ホストに公開する場合は、本サーバー自体は
  認証機構を持たないため、リバースプロキシ (mTLS、OAuth Proxy など) や
  内部ネットワーク制限で経路を絞ること (要件 5.4)。
- DNS リバインディング保護は既定で有効。`build_server(allowed_hosts=...)`
  で許可ホストを明示できる。

### HTTP 認証パターン

本サーバは認証を持たない前提なので、HTTP で公開する場合は **手前に
認証層を必ず挟む**。代表的な 3 つのパターンを記す。

#### パターン A: リバースプロキシ + Bearer トークン (最低限)

社内ネットワークや認証済み経路の上で、MCP クライアントが共有する
シークレットを `Authorization: Bearer …` ヘッダで送る前提。
nginx 例:

```nginx
server {
    listen 443 ssl http2;
    server_name codesearch.internal;

    ssl_certificate     /etc/letsencrypt/live/codesearch.internal/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/codesearch.internal/privkey.pem;

    # Header-based gate. Token は KMS / Vault などで配布。
    if ($http_authorization != "Bearer ${CODESEARCH_BEARER}") {
        return 401;
    }

    location /mcp/ {
        proxy_pass         http://127.0.0.1:8000/mcp/;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   X-Forwarded-For   $remote_addr;
        # Streamable HTTP は SSE を使うのでバッファリングを止める
        proxy_buffering    off;
        proxy_read_timeout 1h;
    }
}
```

クライアント側はリクエストに固定 Bearer を載せる (
`mcpServers.<name>.headers` 等の設定キーが利用できる場合に限る。
未対応のホストでは pattern B のような L4 制限が現実解)。

#### パターン B: mTLS (組織内 PKI で発行した証明書を要求)

社内 CA があるなら、proxy で **クライアント証明書必須** に倒すのが
最も堅い。

```nginx
server {
    listen 443 ssl http2;
    server_name codesearch.internal;

    ssl_certificate           /etc/codesearch/server.crt;
    ssl_certificate_key       /etc/codesearch/server.key;
    ssl_client_certificate    /etc/codesearch/internal-ca.crt;
    ssl_verify_client         on;
    ssl_verify_depth          2;

    location /mcp/ {
        proxy_pass         http://127.0.0.1:8000/mcp/;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-SSL-Subject     $ssl_client_s_dn;
        proxy_buffering    off;
        proxy_read_timeout 1h;
    }
}
```

クライアント側は OS / ブラウザの証明書ストアまたは `httpx`/`mcp` SDK
の `cert=("client.crt","client.key")` 渡しで照合させる。

#### パターン C: OAuth/OIDC リバースプロキシ (oauth2-proxy など)

IdP 連携 (Google Workspace / Azure AD / Okta) で人ベースの認証を
かけたい場合は、[`oauth2-proxy`](https://oauth2-proxy.github.io/oauth2-proxy/)
等を nginx の前段に置く。MCP クライアント側は OAuth トークンを
扱える実装に限られるため、現状は **対話チャットアプリを社内 SSO に
直接統合する組織向け** の選択肢。

### 共通の注意

- 本サーバの DNS リバインディング保護 (`allowed_hosts` / `allowed_origins`)
  は **転送後の `Host` ヘッダ** を見るため、リバプロから `Host` を
  上書きする場合は CLI の `--host` と整合させる (例: nginx が
  `Host codesearch.internal` を渡すなら、`build_server` の許可ホストに
  同じ値を含めるか、proxy で `Host 127.0.0.1:8000` に書き換える)。
- `secrets.toml` (token / ssh_key) は **サーバ側の Git 認証用** であって
  クライアントの認証には使わない。混同しない。
- Streamable HTTP は SSE を含むため、proxy 側で **長時間 keep-alive と
  バッファ無効化** (`proxy_buffering off;` / `proxy_read_timeout 1h;`)
  を必ず設定する。

## 配備パターン

- 単一ホスト (cron + stdio): cron で `codesearch-sync`、クライアントは
  stdio で `codesearch-mcp serve --transport stdio` を起動。
- 単一ホスト (常駐 + HTTP): `--enable-scheduler` を付けて HTTP で公開。
- Kubernetes: 同期は CronJob、サービスは Deployment、ワークスペースは
  PVC。secrets は Secret から `subPath` でマウントして 600 を保つ。
