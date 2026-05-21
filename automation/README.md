# 介護施設 営業自動化パイプライン

ハートページ（heartpage.jp）から介護施設を収集し、採用ページの弱点をスコアリングして
パーソナライズされた営業メール・フォームを自動送信するツールです。

スマホ承認UI（approver_server.py）を使えば、
PCで候補を溜めておき、外出先のスマホで1件ずつ「承認 / 却下」できます。

---

## ファイル構成

| ファイル | 役割 |
|----------|------|
| `run_pipeline.py` | メインパイプライン（施設収集 → スコアリング → メール/フォーム送信） |
| `approver_server.py` | スマホ承認サーバー（Flask）— 承認後にメール/フォームを送信 |
| `directory_scraper.py` | heartpage.jp から施設名・電話を収集し、DDGで公式URLを検索 |
| `researcher.py` | 施設サイトのスクレイピング・メールアドレス抽出 |
| `scorer.py` | 採用ページのスコアリング（0〜100点、ランクA/B/C） |
| `email_generator.py` | パーソナライズ営業メールの生成 |
| `email_sender.py` | GmailSMTPでのメール送信 |
| `form_submitter.py` | 施設の問い合わせフォームへの自動入力・送信 |
| `sales_guard.py` | 営業禁止サイトの検出（Pass 1: 正規表現） |
| `quality_checker.py` | 送信先の品質2重チェック（Pass 1: 内部ルール / Pass 2: CODEX） |
| `sent_log.py` | 送信済みログの管理・日次上限チェック・重複防止 |
| `config.py` | エリア・施設タイプ・送信設定 |

---

## セットアップ（初回のみ・5分）

### 1. Pythonのインストール確認

```bash
python --version
# Python 3.11 以上推奨
```

### 2. ライブラリのインストール

```bash
cd "C:/Users/okahara/Desktop/ponomedia 介護採用事業専用/care-recruit-growth/automation"
pip install -r requirements.txt
```

### 3. .envファイルの作成

`.env.example` を `.env` にコピーして編集します。

```bash
copy .env.example .env
```

`.env` をメモ帳で開いて入力：

```
GMAIL_ADDRESS=あなたのgmail@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
SENDER_NAME=PonoMedia 介護採用支援
SERVICE_LP_URL=https://your-netlify-url.netlify.app
SAMPLE_SITE_URL=https://your-sample-site.netlify.app
```

#### Gmailアプリパスワードの取得

1. https://myaccount.google.com/security を開く
2. **「2段階認証プロセス」** を有効化
3. 最下部の **「アプリパスワード」** をクリック
4. アプリ: **メール** / デバイス: **Windowsコンピュータ** → 「生成」
5. 表示された16桁のパスワードを `GMAIL_APP_PASSWORD` に入力

---

## 使い方

### パターン1: その場で送信（通常モード）

```bash
# テスト実行（メール送信なし・まずはこれ）
python run_pipeline.py --dry-run

# 本番実行
python run_pipeline.py

# 特定エリアのみ
python run_pipeline.py --area 千葉県八千代市

# ランクAのみ（最優先見込み客だけ）
python run_pipeline.py --rank-filter A

# 処理件数を絞る
python run_pipeline.py --max-facilities 10 --dry-run
```

### パターン2: スマホ承認モード（推奨）

外出先のスマホで1件ずつ確認しながら送信できます。

**Step 1: 候補をキューに溜める（PC）**

```bash
python run_pipeline.py --queue-mode --max-facilities 100
```

→ `output/approval_queue.json` に候補が保存されます（この段階では送信しない）

**Step 2: 承認サーバーを起動（PC）**

```bash
python approver_server.py
```

→ 起動時にスマホ用URLが表示されます（例: `http://192.168.1.x:5050`）

**Step 3: スマホで承認**

1. PCと同じWiFiに接続したスマホでブラウザを開く
2. 表示されたURLにアクセス
3. 各施設の情報・メール文面を確認して「✅ 承認して送信」または「✗ 却下」

キューの残数が20件を切ると、自動的にパイプラインが追加収集します。

---

## ランクの意味

| ランク | スコア | 意味 | 対応 |
|--------|--------|------|------|
| A | 0〜39点 | 採用ページがほぼない・非常に弱い | 最優先アプローチ |
| B | 40〜69点 | 一部あるが不完全 | アプローチ対象 |
| C | 70〜100点 | 採用ページが充実している | スキップ |

---

## 品質チェックの仕組み（2重ガード）

### Pass 1: 内部ルールベース（全件・高速）
- NGドメイン（ポータルサイト・求人サイト）を除外
- 非.jpドメインは要確認扱い
- 介護・福祉キーワードがサイト上にあるか確認
- 施設名がサイト上で確認できるか確認

### Pass 2: CODEX CLI（グレー判定のみ・詳細）
- Pass 1で判断できなかったものをCODEXで第三者確認
- `PASS` / `FAIL` / `REVIEW` で判定

### 営業禁止ガード（SalesGuard）
- Pass 1: スクレイピング時に正規表現で検出
- Pass 2: approver_server.py 承認時にCODEXで独立確認
- どちらかで「禁止」が検出された場合は絶対に送信しない

---

## エリア設定（config.py）

```python
TARGET_AREAS = [
    # (表示名, heartpage_area_id) のタプル
    # heartpageに対応エリアがない場合は None（DDGフォールバック）
    ("千葉県千葉市",   "chiba"),
    ("千葉県船橋市",   "funabashi"),
    ("東京都足立区",   None),   # DDGで検索
]
```

heartpageエリアID例:
- 千葉: `chiba` `ichikawa` `funabashi` `narashino` `kashiwa` `yachiyo` `urayasu`
- 東京: `edogawa` `koto` `itabashi` `nerima` `tokyoota` `setagaya` `suginami` `shinagawa`

---

## 送信ログ

`output/sent_log.json` に全送信履歴が記録されます。

- 同じURL・メール・施設名への再送信を自動ブロック
- 同一ドメイン（グループ施設）への重複送信もブロック
- 1日の送信上限: **20件**（スパム防止）

---

## 出力CSV

`output/results_YYYYMMDD_HHMMSS.csv` にスコアリング・送信結果が保存されます。

| カラム名 | 内容 |
|----------|------|
| timestamp | 処理日時 |
| facility_name | 施設名 |
| facility_type | 施設種別 |
| area | エリア |
| url | 施設サイトURL |
| rank | A / B / C |
| score | スコア（0〜100） |
| has_hiring_page | 採用ページあり？ |
| has_form | 応募フォームあり？ |
| weakness_reasons | 弱点の詳細 |
| contact_email | 取得したメールアドレス |
| email_subject | 送信した件名 |
| email_sent | メール送信済み？ |
| form_submitted | フォーム送信済み？ |
| contact_method | 送信方法（email / form / queued / blocked / none） |
| notes | 備考 |

---

## 注意事項

- **送信間隔は30秒以上あける**（config.py の `WAIT_BETWEEN_EMAILS`）
- **dry-runで内容確認してから本番実行**
- **採用保証の表現は絶対に使わない**（法的リスク）
- **robots.txtを尊重する**（`WAIT_BETWEEN_REQUESTS` は2秒以上）
- **取得したメールアドレスはアウトリーチ目的のみに使用**

---

## トラブルシューティング

### `ModuleNotFoundError` が出る
```bash
pip install -r requirements.txt
```

### Gmail認証エラーが出る
- 2段階認証が有効か確認
- 通常のGmailパスワードではなくアプリパスワードを使用しているか確認

### DuckDuckGo検索でエラーが出る
- レート制限の可能性があります。しばらく待ってから再実行
- `pip install --upgrade duckduckgo-search`

### approver_serverが起動しない
```bash
pip install flask
```
