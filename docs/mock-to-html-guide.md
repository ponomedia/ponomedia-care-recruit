# モック→HTML再現ガイド — モックアップ画像からHTML/CSSへの変換手順

最終更新: 2026-05-17

---

## 概要

このガイドは、Codex imagegen で生成・クライアント承認済みのモックアップ画像を、
HTML/CSSで忠実に再現するための手順・判断基準・確認方法を定めたものです。

**エンジニアはこのガイドを読んでから実装を開始すること。**

---

## 基本姿勢

1. **モックは仕様書である**
   - 承認済みモックに書かれた内容を、創作の余地なく再現するのが基本
   - 「より良いと思うデザイン」への変更は、担当者の承認なしに行わない

2. **スマホファースト**
   - まずスマホ版（375px）を完成させ、その後 PC版（1200px）に拡張する
   - CSSはモバイルベースのスタイルを先に書き、メディアクエリで上書きする

3. **モックと完全一致よりも「意図の再現」を優先**
   - 画像生成ツールの限界でピクセル単位の再現は困難
   - 重要なのは「セクション構成・カラー・大小関係・CTA位置」の再現

---

## STEP 1 — モック画像の読み込みと分析

実装前に以下の情報をモックから読み取る。

### 1-1. セクション構成の確認

モックを縦に見て、上から順にセクション名と内容をリストアップする。

```
例：
01. ヘッダー（ロゴ左・電話中・CTAボタン右）
02. ファーストビュー（背景写真・キャッチコピー・CTAボタン）
03. 求人サマリー（3カラム・アイコン付き）
04. 職種カード（2カラム）
05. 施設紹介（テキスト左・写真右）
06. FAQ（縦積みリスト）
07. 応募CTA（ボタン大・電話番号）
08. フッター（施設情報）
```

### 1-2. カラーの抽出

モック画像から以下のカラーを特定する。

| 用途 | カラーコード（HEX）|
|------|-----------------|
| CTAボタン背景色 | |
| CTAボタン文字色 | |
| ページ背景色（主） | |
| セクション背景色（交互表示の場合） | |
| メイン見出し色 | |
| 本文テキスト色 | |
| アクセントカラー（装飾・アイコン等） | |
| リンク色 | |
| フッター背景色 | |

**カラー抽出方法：**
- macOS: Digital Color Meter
- Windows: PowerToys / Color Picker
- ブラウザ: DevTools > Elements > カラーピッカー（CSSが既知の場合）
- Figma / PhotoShop が使える場合はスポイトツール

### 1-3. スペーシングの推定

モック画像から目視でスペーシングを推定する。
厳密な数値より「大・中・小」の相対感を掴むことが重要。

| 場所 | 推定値 | 実装値 |
|------|-------|-------|
| セクション上下余白 | 60〜80px | |
| コンテナ左右余白（スマホ） | 16〜20px | |
| 見出しと本文の間隔 | 16〜24px | |
| カード内パディング | 20〜24px | |
| ボタンのパディング | 縦14px / 横32px 程度 | |

---

## STEP 2 — HTML構造の設計

### 2-1. セマンティックHTMLを使う

```html
<!-- 推奨構造 -->
<header>...</header>
<main>
  <section id="hero">...</section>
  <section id="summary">...</section>
  <section id="jobs">...</section>
  <section id="about">...</section>
  <section id="faq">...</section>
  <section id="apply">...</section>
</main>
<footer>...</footer>
```

### 2-2. セクションIDの命名規則

| セクション | 推奨ID |
|---------|--------|
| ヘッダー | header（タグそのもの） |
| ファーストビュー | hero |
| 求人サマリー | summary |
| 職種一覧 | jobs |
| 施設紹介 | about |
| スタッフの声 | voice |
| 1日のスケジュール | schedule |
| 待遇・福利厚生 | benefits |
| FAQ | faq |
| 採用の流れ | flow |
| 応募CTA | apply |
| フッター | footer（タグそのもの） |

### 2-3. クラス命名規則

BEM（Block Element Modifier）を採用する。

```css
/* Block */
.job-card { }

/* Element */
.job-card__title { }
.job-card__description { }
.job-card__link { }

/* Modifier */
.job-card--featured { }
.btn--primary { }
.btn--secondary { }
```

---

## STEP 3 — CSS実装の手順

### 3-1. CSSの書き順（ファイル構成）

```css
/* 1. リセット・基本設定 */
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: ...; color: ...; background: ...; }

/* 2. 共通パーツ */
.container { max-width: 1200px; margin: 0 auto; padding: 0 20px; }
.btn { ... }
.btn--primary { ... }
.section-title { ... }

/* 3. セクションごとのスタイル（上から順） */
/* header */
/* hero */
/* summary */
/* jobs */
/* about */
/* faq */
/* apply */
/* footer */

/* 4. メディアクエリ（タブレット以上） */
@media (min-width: 768px) { ... }

/* 5. メディアクエリ（デスクトップ以上） */
@media (min-width: 1200px) { ... }
```

### 3-2. レスポンシブの基本設定

```css
/* スマホ（375px〜）: デフォルト */
.jobs-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* タブレット（768px〜） */
@media (min-width: 768px) {
  .jobs-grid {
    flex-direction: row;
    flex-wrap: wrap;
  }
  .job-card {
    width: calc(50% - 8px);
  }
}

/* デスクトップ（1200px〜） */
@media (min-width: 1200px) {
  .job-card {
    width: calc(33.333% - 12px);
  }
}
```

---

## STEP 4 — セクション別 実装チェックポイント

### ヘッダー

- [ ] スマホで1行に ロゴ / 電話番号 / CTAボタン が収まっている
- [ ] 電話番号が `<a href="tel:XXXXXXXXXX">` になっている
- [ ] スクロールに追随する sticky ヘッダーの場合、`position: sticky; top: 0;` を設定
- [ ] ヘッダーが他のコンテンツに重ならない高さ設定

### ファーストビュー（ヒーロー）

- [ ] 背景画像が `background-image` で設定されており、`background-size: cover` になっている
- [ ] 背景画像の上にオーバーレイ（半透明の黒）でテキストが読めるようにしている
- [ ] キャッチコピーのフォントサイズがスマホで22〜28px程度
- [ ] CTAボタンがファーストビュー内に必ず1つある
- [ ] スマホでは最低500px以上の高さが確保されている

### 求人サマリー（3カラム）

- [ ] スマホでは縦積みになっている
- [ ] 各項目にアイコンまたは絵文字（シンプルな場合）がある
- [ ] 数値（月給・時給等）が大きく、単位が小さく表示されている

### 職種カード

- [ ] カードに shadow（`box-shadow`）が設定されている
- [ ] 各カードに「詳細を見る」リンクがある
- [ ] スマホは1カラム・PCは2〜3カラムになっている
- [ ] カードのホバー時に軽い変化がある（`transform: translateY(-4px)`等）

### FAQ

- [ ] 質問文が太字または目立つスタイルになっている
- [ ] 回答文がインデントまたは区切りで視覚的に区別されている
- [ ] アコーディオン実装を行う場合は、JavaScript で toggle を実装
- [ ] 最低5件以上の質問が含まれている

### 応募CTA（最終）

- [ ] CTAボタンが大きく（スマホ幅の80〜90%）中央配置
- [ ] ボタンの色がページ内で最も目立つ
- [ ] 電話番号・LINE等の代替導線も記載
- [ ] ボタン下に「見学だけでもOKです」等の安心文言

### フッター

- [ ] 施設名・住所・電話番号が含まれている
- [ ] コピーライト表記がある（`© 2026 施設名`）
- [ ] リンクがある場合、外部リンクに `rel="noopener noreferrer"` が設定されている

---

## STEP 5 — 構造化データ・メタ情報の実装

### 5-1. head タグに必要な要素

```html
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">

  <!-- SEO -->
  <title>介護職員 募集｜○○施設（○○市）</title>
  <meta name="description" content="○○市の介護施設○○では介護職員を募集しています。月給○○万円〜、未経験歓迎。見学随時受付中。">

  <!-- OGP -->
  <meta property="og:title" content="介護職員 募集｜○○施設">
  <meta property="og:description" content="月給○○万円〜。未経験歓迎。○○市の介護施設です。">
  <meta property="og:image" content="https://example.com/ogp.jpg">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://example.com/recruit">

  <!-- GA4 -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', 'G-XXXXXXXXXX');
  </script>
</head>
```

### 5-2. JobPosting 構造化データ

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "title": "介護職員（介護士）",
  "description": "○○市の介護施設○○では介護職員を募集しています。未経験の方も研修制度が整っているので安心して働けます。",
  "datePosted": "2026-05-17",
  "validThrough": "2026-12-31",
  "employmentType": "FULL_TIME",
  "hiringOrganization": {
    "@type": "Organization",
    "name": "○○施設",
    "sameAs": "https://example.com"
  },
  "jobLocation": {
    "@type": "Place",
    "address": {
      "@type": "PostalAddress",
      "streetAddress": "○○1-2-3",
      "addressLocality": "○○市",
      "addressRegion": "○○県",
      "postalCode": "000-0000",
      "addressCountry": "JP"
    }
  },
  "baseSalary": {
    "@type": "MonetaryAmount",
    "currency": "JPY",
    "value": {
      "@type": "QuantitativeValue",
      "minValue": 200000,
      "maxValue": 280000,
      "unitText": "MONTH"
    }
  }
}
</script>
```

---

## STEP 6 — 実装後のセルフチェック

### 6-1. 視覚的なモック照合

モック画像を横に表示しながら、ブラウザの実装と以下を比較する。

| 確認項目 | 確認方法 |
|---------|---------|
| セクション順序がモックと一致 | 縦スクロールしながら比較 |
| CTAボタンの色・形がモックと一致 | 色コードを DevTools で確認 |
| 見出しの大小関係がモックと一致 | 目視確認 |
| カードのカラム数がモックと一致 | スマホ・PC で各確認 |
| 余白のバランスがモックと概ね一致 | 全体スクロールで比較 |

### 6-2. 動作確認

| 確認項目 | 確認方法 |
|---------|---------|
| フォームがGoogle フォームに遷移するか | クリックして確認 |
| 電話番号をタップで発信できるか | スマホ実機で確認 |
| 画像が全て読み込まれているか | ブラウザで確認（遅延読み込みも） |
| スクロールがスムーズか | 実機で確認 |

### 6-3. Codex レビューへ提出

自己チェック完了後、`docs/codex-review-checklist.md` に沿ってCodexレビューを依頼する。

---

## よくある実装ミスと対処

| ミス | 原因 | 対処 |
|------|------|------|
| スマホで横スクロールが発生 | 要素が幅を超えている | `overflow-x: hidden` + 幅の見直し |
| 画像が縦横比崩れで表示 | `width: 100%` のみ指定 | `object-fit: cover` を追加 |
| ボタンが小さすぎる | padding不足 | padding-top/bottom を14px以上に |
| フォントが読み込まれない | Google Fonts のURL間違い | link href を確認 |
| 構造化データにエラー | 必須プロパティの欠落 | Googleリッチリザルトテストで確認 |
| OGP画像が表示されない | 画像パスが相対パス | 絶対URLに変更 |
| CTA色がモックと違う | カラーコードの入力ミス | DevTools でコードを確認 |
| セクション間の余白が均等でない | margin/paddingの混在 | padding を section に統一 |

---

## 納品前の最終チェック

実装完了後、`docs/delivery-checklist.md` を開き、全項目にOKがつくことを確認してから納品工程に進む。
