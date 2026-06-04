#!/usr/bin/env python3
"""
build_lp_pack.py
PonoMedia LP (standalone).html から:
 1. React コンポーネントに画像を注入
 2. フォント UUID を Google Fonts CDN に差し替え
 3. sites/lp-pack/index.html に出力

Usage:
    python build_lp_pack.py
"""

import json, base64, gzip, re, os, shutil

INPUT_HTML = r"C:\Users\okahara\Downloads\PonoMedia LP (standalone).html"
OUTPUT_DIR  = r"C:\Users\okahara\Desktop\ponomedia 介護採用事業専用\care-recruit-growth\sites\lp-pack"
OUTPUT_HTML = os.path.join(OUTPUT_DIR, "index.html")
IMGS_DIR    = os.path.join(OUTPUT_DIR, "imgs")

# ── UUIDs of target components (short prefix sufficient for identification) ──
HERO_PREFIX      = "06b24e37"   # HeroVisual + Hero
INDUSTRIES_PREFIX = "5856a1bc"  # PainPoints + Services + Industries

def decode_asset(entry):
    data = base64.b64decode(entry["data"])
    if entry.get("compressed"):
        data = gzip.decompress(data)
    return data.decode("utf-8")

def encode_asset(text, compress=True):
    data = text.encode("utf-8")
    if compress:
        data = gzip.compress(data, mtime=0)
    return base64.b64encode(data).decode("ascii")

def inject_hero_image(text):
    """Add hero-consult.jpg after hero__stats (end of hero__content), before hero__visual."""
    img_block = (
        '\n            <div className="hero__photo" style={{marginTop:"1.5rem"}}>'
        '<img src="imgs/hero-consult.jpg" '
        'alt="採用ページ制作の相談シーン" '
        'style={{width:"100%",borderRadius:"12px",'
        'boxShadow:"0 8px 32px rgba(0,0,0,0.15)",display:"block"}} '
        'loading="eager"/></div>'
    )
    # Exact pattern from decoded component:
    # ...hero__stats>\n...map...\n            </div>\n          </div>\n          <div className="hero__visual">
    target = '            </div>\n          </div>\n          <div className="hero__visual">'
    if target in text:
        return text.replace(target,
            '            </div>' + img_block + '\n          </div>\n          <div className="hero__visual">',
            1)
    print("  WARNING: hero injection fallback used")
    return text.replace(
        '<div className="hero__visual">',
        img_block + '\n          <div className="hero__visual">',
        1,
    )

def inject_industries_image(text):
    """Add industries.jpg between ind__grid and ind__cta in Industries component."""
    img_block = (
        '\n        <div style={{margin:"2rem auto 0",maxWidth:"840px",'
        'borderRadius:"16px",overflow:"hidden",'
        'boxShadow:"0 6px 24px rgba(0,0,0,0.12)"}}>'
        '<img src="imgs/industries.jpg" '
        'alt="介護・保育・建設など多業種の採用ページ制作" '
        'style={{width:"100%",display:"block",maxHeight:"360px",objectFit:"cover"}} '
        'loading="lazy"/></div>'
    )
    # Exact pattern from decoded component:
    # ...))}\n        </div>\n        <div className="ind__cta">
    target = '        </div>\n        <div className="ind__cta">'
    if target in text:
        return text.replace(target,
            '        </div>' + img_block + '\n        <div className="ind__cta">',
            1)
    print("  WARNING: industries injection fallback used")
    return text

def main():
    print("Reading LP file...")
    with open(INPUT_HTML, "r", encoding="utf-8") as f:
        content = f.read()

    # ── Parse manifest ──────────────────────────────────────────────────────
    m = re.search(r'<script type="__bundler/manifest">(.*?)</script>', content, re.DOTALL)
    if not m:
        print("ERROR: manifest not found"); return
    manifest = json.loads(m.group(1))
    print(f"Assets: {len(manifest)} total")

    # ── Check images ─────────────────────────────────────────────────────────
    os.makedirs(IMGS_DIR, exist_ok=True)
    img1 = os.path.join(IMGS_DIR, "hero-consult.jpg")
    img2 = os.path.join(IMGS_DIR, "industries.jpg")
    has_img1 = os.path.exists(img1)
    has_img2 = os.path.exists(img2)
    print(f"  hero-consult.jpg: {'OK' if has_img1 else 'MISSING'}")
    print(f"  industries.jpg:   {'OK' if has_img2 else 'MISSING'}")

    modified = dict(manifest)

    # ── Inject images into components ────────────────────────────────────────
    for uuid, entry in manifest.items():
        if "font" in entry.get("mime", "") or "woff" in entry.get("mime", ""):
            continue

        short = uuid.replace("-", "")[:8]

        if short == HERO_PREFIX.replace("-", "") and has_img1:
            text = decode_asset(entry)
            new_text = inject_hero_image(text)
            if new_text != text:
                print(f"  [✓] Hero image injected into {uuid[:8]}")
            else:
                print(f"  [!] Hero injection found no target in {uuid[:8]}")
            modified[uuid] = {**entry,
                              "data": encode_asset(new_text, entry.get("compressed", True))}

        elif short == INDUSTRIES_PREFIX.replace("-", "") and has_img2:
            text = decode_asset(entry)
            new_text = inject_industries_image(text)
            if new_text != text:
                print(f"  [✓] Industries image injected into {uuid[:8]}")
            else:
                print(f"  [!] Industries injection found no target in {uuid[:8]}")
            modified[uuid] = {**entry,
                              "data": encode_asset(new_text, entry.get("compressed", True))}

    # ── Replace font UUIDs with Google Fonts CDN ─────────────────────────────
    # Remove font entries from manifest to slim down the file
    slim_manifest = {k: v for k, v in modified.items()
                     if "font" not in v.get("mime", "") and "woff" not in v.get("mime", "")}
    print(f"  Slimmed manifest: {len(modified)} → {len(slim_manifest)} assets (fonts removed)")

    # Remove @font-face rules that reference UUID blob URLs
    # These are declared in CSS assets — we'll just let the page use system fonts
    # instead, then override with Google Fonts via CDN <link>

    # ── Rebuild HTML ──────────────────────────────────────────────────────────
    new_manifest_json = json.dumps(slim_manifest, ensure_ascii=False, separators=(",", ":"))
    new_content = re.sub(
        r'<script type="__bundler/manifest">.*?</script>',
        f'<script type="__bundler/manifest">{new_manifest_json}</script>',
        content,
        flags=re.DOTALL,
    )

    # Add Google Fonts CDN
    google_fonts = (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700;900&display=swap" rel="stylesheet">'
    )
    new_content = new_content.replace(
        '<meta charset="utf-8">',
        f'<meta charset="utf-8">\n  {google_fonts}',
        1,
    )

    # ── Write output ──────────────────────────────────────────────────────────
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(new_content)

    size_mb = os.path.getsize(OUTPUT_HTML) / 1024 / 1024
    print(f"\nOutput: {OUTPUT_HTML}")
    print(f"Size:   {size_mb:.1f} MB")
    print("Done.")

if __name__ == "__main__":
    main()
