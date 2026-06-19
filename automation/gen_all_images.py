#!/usr/bin/env python3
"""
gen_all_images.py — 全サイト用画像を1枚ずつ順次生成してコピー
"""
import os, subprocess, time, shutil, json, sys

CODEX = r"C:\Users\okahara\AppData\Local\OpenAI\Codex\bin\7dea4a003bc76627\codex.exe"
GEN_DIR = r"C:\Users\okahara\.codex\generated_images"
BASE = r"C:\Users\okahara\Desktop\ponomedia 介護採用事業専用\care-recruit-growth\sites"

# (output_name, prompt_short, [destination_paths])
IMAGES = [
    (
        "consult-new.jpg",
        "photorealistic-natural: Japanese businesswoman late 30s presenting recruitment website mockups on MacBook Pro to two engaged clients across a wooden conference table. Modern bright meeting room, window light casting soft shadows, two coffee cups on table, relaxed professional atmosphere. Shallow depth of field, documentary style. 16:9 landscape.",
        [
            "service-lp/imgs/consult.jpg",
            "service-kensetsu/imgs/consult.jpg",
            "service-hoiku/imgs/consult.jpg",
            "service-inshoku/imgs/consult.jpg",
            "service-butsuryu/imgs/consult.jpg",
            "service-seisou/imgs/consult.jpg",
            "lp-pack/imgs/consult.jpg",
            "lp-pack/imgs/hero-consult.jpg",
        ],
    ),
    (
        "service-lp-hero.jpg",
        "photorealistic-natural: Japanese female social worker early 30s at a clean modern desk, reviewing a laptop showing recruitment data, natural window light from the left, slight focus blur on background office, candid documentary feel, realistic skin and fabric texture. 16:9.",
        ["service-lp/imgs/hero-photo.jpg"],
    ),
    (
        "service-kensetsu-hero.jpg",
        "photorealistic-natural: Japanese construction site foreman mid-40s in white hard hat and orange safety vest reviewing blueprints with young apprentice on active job site. Concrete columns, dust in sunlit air, authentic work environment, slight motion blur on background workers. 16:9.",
        ["service-kensetsu/imgs/hero.jpg"],
    ),
    (
        "service-hoiku-hero.jpg",
        "photorealistic-natural: Japanese nursery teacher late 20s in soft yellow apron sitting cross-legged on colorful play mat, reading picture book aloud to 3 attentive toddlers. Bright classroom, paper crafts on walls, toys scattered naturally, afternoon window light, genuine warm smile. 16:9.",
        ["service-hoiku/imgs/hero.jpg"],
    ),
    (
        "service-inshoku-hero.jpg",
        "photorealistic-natural: Japanese izakaya kitchen, two cooks in white uniforms actively working — one stirring wok with steam rising, another plating dishes. Stainless steel counters, warm overhead lighting, busy authentic restaurant kitchen. Steam motion blur. 16:9.",
        ["service-inshoku/imgs/hero.jpg"],
    ),
    (
        "service-butsuryu-hero.jpg",
        "photorealistic-natural: Japanese logistics warehouse worker mid-30s in blue company vest confidently scanning barcodes on cardboard boxes moving on conveyor belt. Modern fulfillment center, bright fluorescent lighting, forklift visible in background. 16:9.",
        ["service-butsuryu/imgs/hero.jpg"],
    ),
    (
        "service-seisou-hero.jpg",
        "photorealistic-natural: Japanese female cleaning professional in her 40s in green company uniform operating commercial floor buffer machine in marble lobby of modern Tokyo office building. Polished reflective floor, natural confident posture, morning light from glass entrance. 16:9.",
        ["service-seisou/imgs/hero.jpg"],
    ),
    (
        "sample-kaigo-hero.jpg",
        "photorealistic-natural: Japanese female caregiver mid-30s in light blue scrubs gently holding the hand of an elderly woman in a wheelchair at a small warm day service facility. Soft afternoon sunlight through window, houseplants visible, intimate caring moment, genuine warm expression, documentary feel. 16:9.",
        ["sample-care-recruit/imgs/hero.jpg"],
    ),
    (
        "sample-kensetsu-hero.jpg",
        "photorealistic-natural: Confident Japanese male construction worker late 20s in white hard hat and work clothes examining renovation inside residential apartment. Paint-spattered walls, exposed pipes visible, natural daylight from bare window, authentic work mess. 16:9.",
        ["sample-kensetsu/imgs/hero.jpg"],
    ),
    (
        "sample-hoiku-hero.jpg",
        "photorealistic-natural: Japanese female preschool teacher in pink apron kneeling at child height, genuinely laughing with group of 4 toddlers on bright outdoor playground. Real setting with sandbox and climbing structure, natural midday light, candid joyful moment. 16:9.",
        ["sample-hoiku/imgs/hero.jpg"],
    ),
    (
        "sample-inshoku-hero.jpg",
        "photorealistic-natural: Japanese male chef mid-30s in pristine white uniform carefully garnishing beautifully plated Japanese set meal in real restaurant kitchen. Stainless surfaces, hanging utensils, focused professional expression, warm overhead light catching steam. 16:9.",
        ["sample-inshoku/imgs/hero.jpg"],
    ),
    (
        "sample-butsuryu-hero.jpg",
        "photorealistic-natural: Japanese delivery driver early 30s in navy company uniform opening rear door of white delivery van on suburban Tokyo street. Stacked packages inside, clipboard in hand, sunny residential neighborhood, natural candid moment. 16:9.",
        ["sample-butsuryu/imgs/hero.jpg"],
    ),
    (
        "sample-seisou-hero.jpg",
        "photorealistic-natural: Japanese cleaning professional woman 50s in neat green uniform using telescopic window squeegee on large floor-to-ceiling glass panels in modern Tokyo office. Reflected cityscape on glass, confident posture, morning light. 16:9.",
        ["sample-seisou/imgs/hero.jpg"],
    ),
    (
        "lp-industries.jpg",
        "photorealistic-natural: Five Japanese workers in different industry uniforms standing casually together outdoors on sunny day — construction hard hat, blue medical scrubs, white chef uniform, delivery vest, business casual. Natural group photo, genuine expressions, bright outdoor setting, slight variation in poses. 16:9.",
        ["lp-pack/imgs/industries.jpg"],
    ),
]

def get_existing_uuids():
    return set(os.listdir(GEN_DIR)) if os.path.exists(GEN_DIR) else set()

def get_new_image(before_uuids):
    """Find the newest PNG added since before_uuids was captured."""
    after = set(os.listdir(GEN_DIR)) if os.path.exists(GEN_DIR) else set()
    new_uuids = after - before_uuids
    candidates = []
    for uid in new_uuids:
        folder = os.path.join(GEN_DIR, uid)
        if not os.path.isdir(folder): continue
        for f in os.listdir(folder):
            if f.startswith("ig_") and f.endswith(".png"):
                fp = os.path.join(folder, f)
                candidates.append((os.path.getmtime(fp), fp))
    # Also check latest from ALL (in case UUID didn't change)
    all_imgs = []
    for uid in after:
        folder = os.path.join(GEN_DIR, uid)
        if not os.path.isdir(folder): continue
        for f in os.listdir(folder):
            if f.startswith("ig_") and f.endswith(".png"):
                fp = os.path.join(folder, f)
                all_imgs.append((os.path.getmtime(fp), fp))
    all_imgs.sort(reverse=True)
    # Prefer new_uuid candidates
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]
    return all_imgs[0][1] if all_imgs else None

def run_one(name, prompt, dests, delay_before=0):
    if delay_before > 0:
        print(f"  ⏳ Waiting {delay_before}s before next generation...")
        time.sleep(delay_before)

    print(f"\n🎨 Generating: {name}")
    before = get_existing_uuids()
    mtime_before = max(
        (os.path.getmtime(os.path.join(GEN_DIR, uid, f))
         for uid in os.listdir(GEN_DIR) if os.path.isdir(os.path.join(GEN_DIR, uid))
         for f in os.listdir(os.path.join(GEN_DIR, uid)) if f.endswith(".png")),
        default=0
    ) if os.path.exists(GEN_DIR) else 0

    cmd = [CODEX, "-c", "model=gpt-5.5", "exec",
           f"Use image_gen to create ONE image: {prompt}\nDo not copy or move the file."]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                                encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        print(f"  ⚠ Timeout for {name}")
        return False

    output = result.stdout + result.stderr
    if "TooManyRequests" in output or "rate" in output.lower():
        print(f"  ⚠ Rate limited. Waiting 90s...")
        time.sleep(90)
        # Retry once
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                                    encoding='utf-8', errors='replace')
        except subprocess.TimeoutExpired:
            print(f"  ⚠ Timeout on retry for {name}")
            return False
        output = result.stdout + result.stderr

    if "server error" in output.lower() or "failed twice" in output.lower():
        print(f"  ✗ Server error for {name}")
        return False

    # Find new image
    time.sleep(2)  # Let FS settle
    img_path = get_new_image(before)

    # Also try by mtime
    if not img_path:
        all_imgs = []
        for uid in os.listdir(GEN_DIR):
            folder = os.path.join(GEN_DIR, uid)
            if not os.path.isdir(folder): continue
            for f in os.listdir(folder):
                if f.endswith(".png"):
                    fp = os.path.join(folder, f)
                    mt = os.path.getmtime(fp)
                    if mt > mtime_before:
                        all_imgs.append((mt, fp))
        all_imgs.sort(reverse=True)
        if all_imgs:
            img_path = all_imgs[0][1]

    if not img_path:
        print(f"  ✗ No new image found for {name}")
        return False

    sz = os.path.getsize(img_path) // 1024
    print(f"  ✓ Generated: {os.path.basename(img_path)} ({sz}KB)")

    # Copy to all destinations
    for rel in dests:
        dst = os.path.join(BASE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(img_path, dst)
        print(f"  → {rel}")

    return True

def main():
    start_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    print(f"Starting from index {start_idx}. Total images: {len(IMAGES)}")

    for i, (name, prompt, dests) in enumerate(IMAGES):
        if i < start_idx:
            print(f"  [skip] {name}")
            continue

        # 30s gap between each to avoid rate limits
        delay = 30 if i > start_idx else 0
        success = run_one(name, prompt, dests, delay_before=delay)

        if not success:
            print(f"  ⚠ Failed: {name}. Continuing with next...")

    print("\n✅ Done. Run git commit to deploy.")

if __name__ == "__main__":
    main()
