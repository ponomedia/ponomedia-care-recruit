#!/usr/bin/env python3
"""
fix_missing_images.py
重複・誤配置になった画像を正しいCodexプロンプトで再生成して正しい場所にコピー。
"""
import os, subprocess, time, shutil

CODEX = r"C:\Users\okahara\AppData\Local\OpenAI\Codex\bin\7dea4a003bc76627\codex.exe"
GEN_DIR = r"C:\Users\okahara\.codex\generated_images"
BASE = r"C:\Users\okahara\Desktop\ponomedia 介護採用事業専用\care-recruit-growth\sites"

IMAGES = [
    (
        "sample-inshoku-hero",
        "photorealistic-natural: Japanese male chef mid-30s in pristine white uniform carefully garnishing beautifully plated Japanese set meal in real restaurant kitchen. Stainless surfaces, hanging utensils, focused professional expression, warm overhead light catching steam. 16:9.",
        ["sample-inshoku/imgs/hero.jpg"],
    ),
    (
        "sample-butsuryu-hero",
        "photorealistic-natural: Japanese delivery driver early 30s in navy company uniform opening rear door of white delivery van on suburban Tokyo street. Stacked packages inside, clipboard in hand, sunny residential neighborhood, natural candid moment. 16:9.",
        ["sample-butsuryu/imgs/hero.jpg"],
    ),
    (
        "sample-seisou-hero",
        "photorealistic-natural: Japanese cleaning professional woman 50s in neat green uniform using telescopic window squeegee on large floor-to-ceiling glass panels in modern Tokyo office. Reflected cityscape on glass, confident posture, morning light. 16:9.",
        ["sample-seisou/imgs/hero.jpg"],
    ),
    (
        "lp-industries",
        "photorealistic-natural: Five Japanese workers in different industry uniforms standing casually together outdoors on sunny day — construction hard hat, blue medical scrubs, white chef uniform, delivery vest, business casual. Natural group photo, genuine expressions, bright outdoor setting, slight variation in poses. 16:9.",
        ["lp-pack/imgs/industries.jpg"],
    ),
]


def get_newest_image(before_mtime):
    best = None
    best_mt = before_mtime
    if not os.path.exists(GEN_DIR):
        return None
    for uid in os.listdir(GEN_DIR):
        folder = os.path.join(GEN_DIR, uid)
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if f.startswith("ig_") and f.endswith(".png"):
                fp = os.path.join(folder, f)
                mt = os.path.getmtime(fp)
                if mt > best_mt:
                    best_mt = mt
                    best = fp
    return best


def run_one(label, prompt, dests):
    print(f"\n{'='*60}")
    print(f"Generating: {label}")

    # Record mtime before generation
    before_mtime = 0
    if os.path.exists(GEN_DIR):
        for uid in os.listdir(GEN_DIR):
            folder = os.path.join(GEN_DIR, uid)
            if not os.path.isdir(folder):
                continue
            for f in os.listdir(folder):
                if f.endswith(".png"):
                    fp = os.path.join(folder, f)
                    mt = os.path.getmtime(fp)
                    if mt > before_mtime:
                        before_mtime = mt

    cmd = [
        CODEX, "-c", "model=gpt-5.5", "exec",
        f"Use image_gen to create ONE image: {prompt}\nDo not copy or move the file."
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=240,
                                encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT for {label}")
        return False

    output = result.stdout + result.stderr
    if "TooManyRequests" in output or "rate" in output.lower():
        print("  Rate limited. Waiting 120s...")
        time.sleep(120)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=240,
                                    encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT on retry for {label}")
            return False
        output = result.stdout + result.stderr

    # Wait for FS to settle
    time.sleep(3)

    img = get_newest_image(before_mtime)
    if not img:
        print(f"  No new image found for {label}")
        print(f"  STDOUT: {result.stdout[:200]}")
        return False

    sz = os.path.getsize(img) // 1024
    print(f"  Generated: {os.path.basename(img)} ({sz}KB)")

    for rel in dests:
        dst = os.path.join(BASE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(img, dst)
        print(f"  -> {rel}")

    return True


def main():
    for i, (label, prompt, dests) in enumerate(IMAGES):
        if i > 0:
            print("Waiting 45s to avoid rate limit...")
            time.sleep(45)
        ok = run_one(label, prompt, dests)
        if not ok:
            print(f"  FAILED: {label}")

    print("\n=== Done ===")
    for label, _, dests in IMAGES:
        for rel in dests:
            p = os.path.join(BASE, rel)
            if os.path.exists(p):
                sz = os.path.getsize(p) // 1024
                import time as t
                mt = t.strftime('%H:%M:%S', t.localtime(os.path.getmtime(p)))
                print(f"  {rel}: {mt} ({sz}KB)")
            else:
                print(f"  {rel}: MISSING")


if __name__ == "__main__":
    main()
