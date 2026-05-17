# 介護施設 営業自動化パイプライン

DuckDuckGoで介護施設を検索し、採用ページの弱点をスコアリングして、パーソナライズされた営業メールを自動送信するツールです。

---

## セットアップ（初回のみ・5分）

### 1. Pythonのインストール確認

```bash
python --version
# Python 3.11 以上推奨
```

Python 3.11未満の場合は https://www.python.org/downloads/ からインストールしてください。

---

### 2. ライブラリのインストール

```bash
cd "C:/Users/okahara/Desktop/ponomedia 介護採用事業専用/care-recruit-growth/automation"
pip install -r requirements.txt
```

---

### 3. .envファイルの作成

`.env.example` を `.env` にコピーして、Gmailの情報を入力します。

```bash
copy .env.example .env
```

`.env` をメモ帳で開いて編集：

```
GMAIL_ADDRESS=あなたのgmail@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
SENDER_NAME=PonoMedia 介護採用支援
SERVICE_LP_URL=https://your-netlify-url.netlify.app
SAMPLE_SITE_URL=https://your-sample-site.netlify.app
```

---

### Gmailアプリパスワードの取得方法

1. ブラウザで https://myaccount.google.com/security を開く
2. **「2段階認証プロセス」** を有効化する（まだの場合）
3. 2段階認証の設定ページ最下部にある **「アプリパスワード」** をクリック
4. アプリ選択: **「メール」**、デバイス選択: **「Windowsコンピュータ」** を選んで「生成」
5. 表示された **16桁のパスワード**（例: `abcd efgh ijkl mnop`）を `.env` の `GMAIL_APP_PASSWORD` に入力
   - スペースありでもなしでも動作します

> 注意: 通常のGmailパスワードではなく、必ずアプリパスワードを使用してください。

---

### 4. config.pyでターゲットエリアを設定

`config.py` を開いて `TARGET_AREAS` リストに営業したい地域を追加します：

```python
TARGET_AREAS = [
    "千葉県八千代市",
    "千葉県習志野市",
    "千葉県船橋市",
    # ここに追加していく
    "東京都江戸川区",
    "東京都葛飾区",
]
```

---

## 使い方

### テスト実行（メール送信なし・まずはこれ）

```bash
python run_pipeline.py --dry-run
```

実行すると：
- 施設の検索・スクレイピング・スコアリングが行われる
- 生成されるメールの内容がコンソールに表示される
- 実際にはメールは送信されない
- `output/results_YYYYMMDD_HHMMSS.csv` が出力される

---

### 本番実行

```bash
python run_pipeline.py
```

---

### 特定エリアのみ実行

```bash
python run_pipeline.py --area 千葉県八千代市
```

---

### ランクAのみ対象（最優先見込み客だけ）

```bash
python run_pipeline.py --rank-filter A
```

### 処理件数を絞る

```bash
python run_pipeline.py --max-facilities 10 --dry-run
```

---

## ランクの意味

| ランク | スコア | 意味 | 対応 |
|--------|--------|------|------|
| A | 0〜39点 | 採用ページがほぼない・非常に弱い | 最優先アプローチ |
| B | 40〜69点 | 一部あるが不完全 | アプローチ対象 |
| C | 70〜100点 | 採用ページが充実している | スキップ |

スコアが低いほど「採用ページが弱い = PonoMediaのサービスが刺さる見込み客」です。

---

## 出力

`output/` フォルダに `results_YYYYMMDD_HHMMSS.csv` が出力されます。

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
| email_sent | 送信済み？ |
| notes | 備考 |

Googleスプレッドシートにインポートして管理できます。
（スプレッドシート → ファイル → インポート → CSVをアップロード）

---

## フォローアップメールの送り方

1週間後に返信がない場合、`email_generator.py` の `generate_followup_email()` を使ってフォローアップできます。

現在は手動での実行が必要です（将来的に自動化予定）。

---

## 注意事項

- **送信間隔は30秒以上あける**（config.py の `WAIT_BETWEEN_EMAILS`）— スパムフラグ防止
- **Gmailの1日あたり送信上限は約500通**— 一度に大量送信しないこと
- **dry-runで内容確認してから本番実行すること**— メールの文面を必ず事前確認する
- **採用保証の表現は絶対に使わない**— メール本文に「採用保証」「採用できる」等は記載しない（法的リスク）
- **robots.txtを尊重する**— 大量スクレイピングは避け、`WAIT_BETWEEN_REQUESTS` を2秒以上に保つ
- **個人情報の取り扱いに注意**— 取得したメールアドレスはアウトリーチ目的のみに使用する

---

## トラブルシューティング

### `ModuleNotFoundError` が出る

```bash
pip install -r requirements.txt
```

を再実行してください。

### Gmail認証エラーが出る

- Googleアカウントの2段階認証が有効になっているか確認
- `.env` の `GMAIL_APP_PASSWORD` が正しいか確認（16桁、ハイフンなしでもOK）
- 通常のGmailパスワードではなくアプリパスワードを使用しているか確認

### DuckDuckGo検索でエラーが出る

- 短時間に大量のリクエストを送るとレート制限がかかることがあります
- しばらく待ってから再実行してください
- `duckduckgo-search` ライブラリを最新版に更新: `pip install --upgrade duckduckgo-search`

### メールが届かない・迷惑メールに入る

- 件名・本文を変更して自然な文面にする
- 送信先ドメインが存在するか確認する
- Gmailの送信済みボックスで送信状況を確認する
