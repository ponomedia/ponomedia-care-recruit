#!/usr/bin/env python3
"""
extract_lp.py — PonoMedia LP (standalone).html を解析・画像注入・出力
"""
import json, base64, gzip, re, os, shutil, sys

INPUT_HTML = r"C:\Users\okahara\Downloads\PonoMedia LP (standalone).html"
OUTPUT_DIR = r"C:\Users\okahara\Desktop\ponomedia 介護採用事業専用\care-recruit-growth\sites\lp-pack"
OUTPUT_HTML = os.path.join(OUTPUT_DIR, "index.html")

def decode_asset(entry):
    data = base64.b64decode(entry['data'])
    if entry.get('compressed'):
        data = gzip.decompress(data)
    return data.decode('utf-8')

def encode_asset(text, compress=True):
    data = text.encode('utf-8')
    if compress:
        data = gzip.compress(data)
    return base64.b64encode(data).decode('ascii')

def main():
    print("Reading LP file...")
    with open(INPUT_HTML, 'r', encoding='utf-8') as f:
        content = f.read()

    # Parse manifest
    manifest_match = re.search(r'<script type="__bundler/manifest">(.*?)</script>', content, re.DOTALL)
    if not manifest_match:
        print("ERROR: No manifest found")
        return

    manifest = json.loads(manifest_match.group(1))
    print(f"Total assets: {len(manifest)}")

    # Identify non-font assets
    non_font = {k: v for k, v in manifest.items()
                if 'font' not in v.get('mime', '') and 'woff' not in v.get('mime', '')}
    print(f"Non-font assets: {len(non_font)}")

    # Decode each non-font asset and show summary
    decoded = {}
    for uuid, entry in non_font.items():
        try:
            text = decode_asset(entry)
            decoded[uuid] = text
            preview = text[:100].replace('\n', ' ')
            print(f"  {uuid[:8]}: len={len(text)} preview={preview[:80]}")
        except Exception as e:
            print(f"  {uuid[:8]}: ERROR {e}")

    # Find Hero component (contains "採用ページ" or "55,000")
    hero_uuid = None
    easystartfaq_uuid = None
    for uuid, text in decoded.items():
        if '55,000' in text and 'Hero' in text:
            hero_uuid = uuid
        if 'EasyStart' in text or 'かんたん' in text or '3ステップ' in text:
            easystartfaq_uuid = uuid

    print(f"\nHero UUID: {hero_uuid}")
    print(f"EasyStart UUID: {easystartfaq_uuid}")

    # If mode is --inject, inject images
    if '--inject' in sys.argv:
        inject_images(content, manifest, decoded, hero_uuid, easystartfaq_uuid)
    else:
        # Just show component details
        for uuid, text in decoded.items():
            print(f"\n=== {uuid[:8]} ({len(text)} chars) ===")
            print(text[:500])
            print("...")

def inject_images(content, manifest, decoded, hero_uuid, easystartfaq_uuid):
    print("\nInjecting images...")

    # Check which images are available
    imgs_dir = os.path.join(OUTPUT_DIR, "imgs")
    os.makedirs(imgs_dir, exist_ok=True)

    img1_exists = os.path.exists(os.path.join(imgs_dir, "hero-consult.jpg"))
    img2_exists = os.path.exists(os.path.join(imgs_dir, "industries.jpg"))
    print(f"  hero-consult.jpg: {img1_exists}")
    print(f"  industries.jpg: {img2_exists}")

    modified_manifest = dict(manifest)

    # Inject into Hero component
    if hero_uuid and img1_exists:
        hero_text = decoded[hero_uuid]
        # Find a good injection point - after the main headline, add an image
        # Look for the hero section's end or a specific landmark
        inject_html = '''
<div style="margin:2rem auto 0;max-width:680px;border-radius:16px;overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,0.18)">
  <img src="imgs/hero-consult.jpg" alt="採用ページ制作の相談風景" style="width:100%;display:block;object-fit:cover" loading="eager"/>
</div>'''

        # Find HeroVisual component or hero section return statement
        # Insert image before closing of hero content div
        if 'HeroVisual' in hero_text:
            # Inject after HeroVisual component usage
            hero_text = hero_text.replace(
                '</HeroVisual>',
                '</HeroVisual>' + inject_html.replace('\n', ' ')
            )
        else:
            # Try to inject before the CTA buttons
            hero_text = re.sub(
                r'(<div[^>]*class[^>]*cta[^>]*>)',
                inject_html.replace('\n', ' ') + r'\1',
                hero_text, count=1
            )

        entry = manifest[hero_uuid]
        modified_manifest[hero_uuid] = {
            **entry,
            'data': encode_asset(hero_text, entry.get('compressed', True)),
        }
        print(f"  Injected hero image into {hero_uuid[:8]}")

    # Inject into Industries/EasyStart component
    if easystartfaq_uuid and img2_exists:
        comp_text = decoded[easystartfaq_uuid]
        inject_html2 = '''
<div style="margin:2rem auto;max-width:780px;border-radius:16px;overflow:hidden;box-shadow:0 6px 24px rgba(0,0,0,0.14)">
  <img src="imgs/industries.jpg" alt="さまざまな業種の採用ページ制作実績" style="width:100%;display:block;object-fit:cover" loading="lazy"/>
</div>'''

        # Insert before EasyStart section or at start of first section in file
        comp_text = comp_text.replace(
            'function EasyStart',
            inject_html2.replace('\n', ' ') + '\nfunction EasyStart',
            1
        )

        entry = manifest[easystartfaq_uuid]
        modified_manifest[easystartfaq_uuid] = {
            **entry,
            'data': encode_asset(comp_text, entry.get('compressed', True)),
        }
        print(f"  Injected industries image into {easystartfaq_uuid[:8]}")

    # Rebuild the HTML with modified manifest
    new_manifest_json = json.dumps(modified_manifest, ensure_ascii=False)
    new_content = re.sub(
        r'<script type="__bundler/manifest">.*?</script>',
        f'<script type="__bundler/manifest">{new_manifest_json}</script>',
        content,
        flags=re.DOTALL
    )

    # Also replace font UUID @font-face with Google Fonts CDN
    # Add Google Fonts link in <head>
    fonts_cdn = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700;900&display=swap" rel="stylesheet">'
    new_content = new_content.replace('<meta charset="utf-8">', f'<meta charset="utf-8">\n  {fonts_cdn}')

    # Write output
    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"\nOutput written to: {OUTPUT_HTML}")
    print(f"File size: {os.path.getsize(OUTPUT_HTML) / 1024 / 1024:.1f} MB")

if __name__ == '__main__':
    main()
