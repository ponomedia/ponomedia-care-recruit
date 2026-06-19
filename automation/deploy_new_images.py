#!/usr/bin/env python3
"""
deploy_new_images.py
/tmp/pono_imgs/ の新画像を各サイトの imgs/ にコピーしてコミット。
Codex が /tmp に書けなかった場合は generated_images から最新を探してコピー。
"""
import os, shutil, subprocess, sys
from datetime import datetime, timezone

BASE = r"C:\Users\okahara\Desktop\ponomedia 介護採用事業専用\care-recruit-growth\sites"
TMP  = r"C:\tmp\pono_imgs"
GEN  = r"C:\Users\okahara\.codex\generated_images"

# image_name_in_tmp → [(dest_dir, dest_filename), ...]
COPY_MAP = {
    "service-lp-hero.jpg":      [("service-lp",      "imgs/hero-photo.jpg")],
    "service-kensetsu-hero.jpg":[("service-kensetsu", "imgs/hero.jpg")],
    "service-hoiku-hero.jpg":   [("service-hoiku",    "imgs/hero.jpg")],
    "service-inshoku-hero.jpg": [("service-inshoku",  "imgs/hero.jpg")],
    "service-butsuryu-hero.jpg":[("service-butsuryu", "imgs/hero.jpg")],
    "service-seisou-hero.jpg":  [("service-seisou",   "imgs/hero.jpg")],
    "sample-kaigo-hero.jpg":    [("sample-care-recruit","imgs/hero.jpg")],
    "sample-kensetsu-hero.jpg": [("sample-kensetsu",  "imgs/hero.jpg")],
    "sample-hoiku-hero.jpg":    [("sample-hoiku",     "imgs/hero.jpg")],
    "sample-inshoku-hero.jpg":  [("sample-inshoku",   "imgs/hero.jpg")],
    "sample-butsuryu-hero.jpg": [("sample-butsuryu",  "imgs/hero.jpg")],
    "sample-seisou-hero.jpg":   [("sample-seisou",    "imgs/hero.jpg")],
    "consult-new.jpg":          [
        ("service-lp",       "imgs/consult.jpg"),
        ("service-kensetsu", "imgs/consult.jpg"),
        ("service-hoiku",    "imgs/consult.jpg"),
        ("service-inshoku",  "imgs/consult.jpg"),
        ("service-butsuryu", "imgs/consult.jpg"),
        ("service-seisou",   "imgs/consult.jpg"),
        ("lp-pack",          "imgs/consult.jpg"),
    ],
    "lp-industries.jpg":        [("lp-pack", "imgs/industries.jpg")],
}

def get_recent_generated(n=1):
    """Return the n most recently modified image files from generated_images."""
    results = []
    for uid in os.listdir(GEN):
        folder = os.path.join(GEN, uid)
        if not os.path.isdir(folder): continue
        for f in os.listdir(folder):
            if f.startswith("ig_") and f.endswith(".png"):
                fp = os.path.join(folder, f)
                results.append((os.path.getmtime(fp), fp))
    results.sort(reverse=True)
    return [r[1] for r in results[:n]]

def main():
    copied = []
    skipped = []
    used_fallback = []

    os.makedirs(TMP, exist_ok=True)

    for img_name, dests in COPY_MAP.items():
        src = os.path.join(TMP, img_name)
        if not os.path.exists(src):
            print(f"  [!] {img_name} not in /tmp — trying generated_images fallback")
            used_fallback.append(img_name)
            # We'll handle fallback manually after seeing what generated
            skipped.append(img_name)
            continue

        for site, rel in dests:
            dst_dir = os.path.join(BASE, site, os.path.dirname(rel))
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(BASE, site, rel)
            shutil.copy2(src, dst)
            sz = os.path.getsize(dst) // 1024
            print(f"  [✓] {img_name} → {site}/{rel} ({sz}KB)")
            copied.append(dst)

    print(f"\n✓ Copied: {len(copied)} files")
    if skipped:
        print(f"✗ Skipped (not in /tmp): {skipped}")

    # Show recent generated_images for manual fallback
    if skipped:
        print("\nMost recent generated images:")
        for fp in get_recent_generated(20):
            mtime = datetime.fromtimestamp(os.path.getmtime(fp), tz=timezone.utc).strftime('%H:%M:%S')
            print(f"  {mtime} {fp}")

if __name__ == "__main__":
    main()
