#!/usr/bin/env python3
"""
fix_lp_copy.py
全サービスLP の英語eyebrowテキストをより自然な表現に置換。
AI感の原因になっているテンプレートっぽい英語ラベルを削除・日本語化。
"""
import os, re

BASE = r"C:\Users\okahara\Desktop\ponomedia 介護採用事業専用\care-recruit-growth\sites"

SERVICE_DIRS = [
    "service-lp",
    "service-kensetsu",
    "service-hoiku",
    "service-inshoku",
    "service-butsuryu",
    "service-seisou",
]

# (old_text, new_text) — 英語eyebrow → より自然な日本語または削除
REPLACEMENTS = [
    # 英語eyebrowラベル → 日本語
    ('eyebrow">The Reality</span>', 'eyebrow">採用の現実</span>'),
    ('eyebrow">What we make</span>', 'eyebrow">サービス内容</span>'),
    ('eyebrow">About PonoMedia</span>', 'eyebrow">PonoMedia について</span>'),
    ('eyebrow">Pricing</span>', 'eyebrow">料金</span>'),
    ('eyebrow">Flow</span>', 'eyebrow">制作の流れ</span>'),
    ('eyebrow" style="justify-content:center;">FAQ</span>', 'eyebrow" style="justify-content:center;">よくある質問</span>'),
    # SERVICE 01 → 01 (番号だけにしてスッキリさせる)
    ('<span class="svc-num">SERVICE 01</span>', '<span class="svc-num">01</span>'),
    ('<span class="svc-num">SERVICE 02</span>', '<span class="svc-num">02</span>'),
    ('<span class="svc-num">SERVICE 03</span>', '<span class="svc-num">03</span>'),
    # About eyebrow on about-banner section
    ('eyebrow">About PonoMedia\n', 'eyebrow">PonoMedia について\n'),
    # Pricing section - PONOMEDIA パック名を自然に
    ('<span class="price-pkg">PONOMEDIA 採用支援パック</span>',
     '<span class="price-pkg">採用支援ワンパッケージ</span>'),
    # hero-note で英語が入っている場合
    ('hero-eyebrow">介護・福祉施設のための採用支援</span>',
     'hero-eyebrow">介護・福祉施設向けの採用ページ制作</span>'),
    # その他英語eyebrow
    ('eyebrow">Our Strength</span>', 'eyebrow">選ばれる理由</span>'),
    ('eyebrow">Case / Reason</span>', 'eyebrow">こんな施設に選ばれています</span>'),
    ('eyebrow">Service</span>', 'eyebrow">サービス内容</span>'),
    ('eyebrow">Price</span>', 'eyebrow">料金</span>'),
    ('eyebrow">Step</span>', 'eyebrow">制作の流れ</span>'),
    ('eyebrow">Contact</span>', 'eyebrow">お問い合わせ</span>'),
    ('eyebrow">Works</span>', 'eyebrow">制作実績</span>'),
    ('eyebrow">Q&amp;A</span>', 'eyebrow">よくある質問</span>'),
    # hero-eyebrow パターン
    ('hero-eyebrow">建設・内装工事業向けの採用支援</span>',
     'hero-eyebrow">建設・内装業者向けの採用ページ制作</span>'),
    ('hero-eyebrow">保育施設のための採用支援</span>',
     'hero-eyebrow">保育園・認定こども園向けの採用ページ制作</span>'),
    ('hero-eyebrow">飲食・フード業向けの採用支援</span>',
     'hero-eyebrow">飲食店・フード業向けの採用ページ制作</span>'),
    ('hero-eyebrow">物流・運送業向けの採用支援</span>',
     'hero-eyebrow">物流・運送業向けの採用ページ制作</span>'),
    ('hero-eyebrow">清掃・ビルメンテナンス向けの採用支援</span>',
     'hero-eyebrow">清掃・ビルメン向けの採用ページ制作</span>'),
]

def fix_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    changed = False
    for old, new in REPLACEMENTS:
        if old in content:
            content = content.replace(old, new)
            changed = True
            print(f"  → {old[:50]!r}")

    # また、eyebrow内の残存英語フレーズを正規表現でクリーンアップ
    # 例: "eyebrow">Why PonoMedia</span>" など
    def clean_eyebrow(m):
        text = m.group(1)
        # 純粋な英語っぽい（日本語文字なし）eyebrowを識別
        if re.search(r'[ぁ-ん]|[ァ-ン]|[一-龯]', text):
            return m.group(0)  # 日本語含む → そのまま
        # 英語のみのeyebrowは一旦スキップ（個別対応済みのもの以外は触らない）
        return m.group(0)

    if changed:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False

def main():
    total = 0
    for site in SERVICE_DIRS:
        path = os.path.join(BASE, site, "index.html")
        if not os.path.exists(path):
            print(f"[skip] {site}/index.html not found")
            continue
        print(f"\n{site}/index.html")
        if fix_file(path):
            total += 1
            print(f"  ✓ Updated")
        else:
            print(f"  (no changes)")

    print(f"\n✓ Updated {total}/{len(SERVICE_DIRS)} files")

if __name__ == "__main__":
    main()
