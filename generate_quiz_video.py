#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_quiz_video.py
Final fixed, GitHub-Action-compatible quiz video generator (1080x1920).
- TTS per question (Piper preferred, else espeak-ng)
- Pillow textbbox fix for modern Pillow versions
- Correct ffmpeg audio mixing (voices mixed then combined with music)
- Produces quiz_YYYYMMDD_HHMMSS.mp4 in working directory (repo root in Actions)
- Good logging for debugging in CI
"""
from __future__ import annotations
import os
import sys
import json
import random
import shutil
import subprocess
from datetime import datetime
from typing import List, Dict, Optional

# Optional libs
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    PIL_OK = True
except Exception:
    PIL_OK = False

try:
    from gpt4all import GPT4All
    GPT4ALL_OK = True
except Exception:
    GPT4ALL_OK = False

# ---------------- Config ----------------
WIDTH, HEIGHT = 1080, 1920
FPS = 30

MODEL_PATH = "models/ggml-gpt4all-j.bin"
MUSIC_FILE = "music/track1.mp3"
UPLOADED_BG = "/mnt/data/A_2D_digital_graphic_quiz_image_features_a_dark_bl.png"
BG_GEN = "background_generated.png"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

INTRO_DUR = 2.0
COUNT_DUR = 2.5
DISPLAY = {"easy": 2.8, "medium": 3.2, "hard": 3.8, "impossible": 4.0}
REVEAL_DUR = 1.6

PIPER_CANDIDATES = ["./piper/piper", "./piper", "piper"]
PIPER_MODEL_DIRS = ["./piper_models/de_DE-eva_k-x_low", "./piper_models/de_de_eva", "./piper_models"]

# ---------------- Helpers ----------------
def run_capture(cmd: List[str]) -> subprocess.CompletedProcess:
    print("RUN:", " ".join(cmd))
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True)
        if cp.returncode != 0:
            print("Command failed (rc={}): {}".format(cp.returncode, " ".join(cmd)))
            if cp.stdout:
                print("--- stdout ---")
                print(cp.stdout)
            if cp.stderr:
                print("--- stderr ---")
                print(cp.stderr)
        return cp
    except Exception as e:
        print("Exception running command:", e)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=str(e))

def file_ok(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0

def sanitize(s: str) -> str:
    return "".join(ch for ch in s if ord(ch) >= 32).strip()[:240]

# ---------------- Background ----------------
def make_background() -> bool:
    if PIL_OK:
        try:
            img = Image.new("RGB", (WIDTH, HEIGHT), (12,12,20))
            draw = ImageDraw.Draw(img)
            for y in range(HEIGHT):
                t = y / HEIGHT
                r = int(8 + 20*t)
                g = int(10 + 10*t)
                b = int(18 + 40*t)
                draw.line([(0,y),(WIDTH,y)], fill=(r,g,b))
            def gloss(cx,cy,rx,ry,color,alpha):
                layer = Image.new("RGBA", (WIDTH,HEIGHT), (0,0,0,0))
                d = ImageDraw.Draw(layer)
                d.ellipse([cx-rx, cy-ry, cx+rx, cy+ry], fill=color + (int(255*alpha),))
                layer = layer.filter(ImageFilter.GaussianBlur(radius=max(6, rx//10)))
                img.paste(Image.alpha_composite(img.convert("RGBA"), layer), (0,0), layer)
            gloss(int(WIDTH*0.2), int(HEIGHT*0.18), 320, 240, (30,80,200), 0.12)
            gloss(int(WIDTH*0.8), int(HEIGHT*0.34), 420, 320, (180,40,150), 0.09)
            if os.path.isfile(UPLOADED_BG):
                try:
                    ov = Image.open(UPLOADED_BG).convert("RGBA").resize((WIDTH,HEIGHT)).filter(ImageFilter.GaussianBlur(4))
                    ov.putalpha(64)
                    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
                except Exception as e:
                    print("Overlay blending failed:", e)
            img.save(BG_GEN, quality=90)
            return True
        except Exception as e:
            print("Pillow background generation failed:", e)
    # ffmpeg fallback
    cp = run_capture(["ffmpeg","-y","-f","lavfi","-i",f"color=c=#0f0f1e:s={WIDTH}x{HEIGHT}:d=0.1","-frames:v","1",BG_GEN])
    return file_ok(BG_GEN)

# ---------------- Questions (GPT4All + fallback) ----------------
def make_votes(correct_index: int) -> List[int]:
    base = [random.uniform(5,25) for _ in range(4)]
    base[correct_index] += random.uniform(20,40)
    s = sum(base)
    perc = [int(round(x/s*100)) for x in base]
    diff = 100 - sum(perc)
    if diff != 0:
        perc[correct_index] += diff
    return perc

def parse_json_from_text(txt: str):
    if not txt: return None
    s = txt.strip()
    if "[" in s and "]" in s:
        s = s[s.find("["):s.rfind("]")+1]
    try:
        parsed = json.loads(s)
        return parsed if isinstance(parsed, list) else None
    except Exception as e:
        print("JSON parse failed:", e)
        return None

def generate_questions_via_gpt(topic: str):
    if not GPT4ALL_OK or not os.path.isfile(MODEL_PATH):
        return None
    try:
        model = GPT4All(MODEL_PATH)
        prompt = (
            f"Erstelle genau 7 Quizfragen (deutsch) zum Thema '{topic}'. "
            "Gib nur ein JSON-Array zurück. "
            "Item: {\"difficulty\":\"easy|medium|hard|impossible\",\"question\":\"...\",\"options\":[4],\"correct\":0-3}. "
            "Reihenfolge: 3 easy,2 medium,1 hard,1 impossible."
        )
        out = model.generate(prompt, max_tokens=700)
        q = parse_json_from_text(out)
        if q and len(q) == 7:
            for item in q:
                if "correct" not in item:
                    item["correct"] = 0
                if "options" not in item or not isinstance(item["options"], list) or len(item["options"]) != 4:
                    item["options"] = ["A","B","C","D"]
                if "votes" not in item:
                    item["votes"] = make_votes(item["correct"])
            return q
    except Exception as e:
        print("GPT4All generation failed:", e)
    return None

def fallback_questions(topic: str):
    seq = ["easy","easy","easy","medium","medium","hard","impossible"]
    qlist = []
    for dif in seq:
        if dif == "easy":
            qtxt = f"Welches ist ein bekanntes Merkmal von {topic}?"
            opts = [f"{topic} A", f"{topic} B", f"{topic} C", f"{topic} D"]
        elif dif == "medium":
            qtxt = f"Wodurch zeichnet sich {topic} oft aus?"
            opts = ["Merkmal A","Merkmal B","Merkmal C","Merkmal D"]
        elif dif == "hard":
            qtxt = f"Welche historische Entwicklung prägte {topic}?"
            opts = ["Entwicklung A","Entwicklung B","Entwicklung C","Entwicklung D"]
        else:
            qtxt = f"Extrem spezifische Frage zu {topic} (Trickfrage)."
            opts = ["X","Y","Z","W"]
        correct = random.randint(0,3)
        qlist.append({"difficulty": dif, "question": qtxt, "options": opts, "correct": correct, "votes": make_votes(correct)})
    return qlist

def generate_questions(topic: str):
    q = generate_questions_via_gpt(topic)
    if q: return q
    print("Using fallback questions for topic:", topic)
    return fallback_questions(topic)

# ---------------- TTS ----------------
def find_piper_binary():
    for c in PIPER_CANDIDATES:
        if shutil.which(c) or os.path.isfile(c):
            return c
    return None

def synthesize_voice(text: str, out_wav: str) -> Optional[str]:
    text = sanitize(text)
    piper = find_piper_binary()
    if piper:
        model_dir = None
        for d in PIPER_MODEL_DIRS:
            if os.path.isdir(d):
                model_dir = d
                break
        try:
            if model_dir:
                cp = run_capture([piper, "--model", model_dir, "--text", text, "--out", out_wav])
            else:
                cp = run_capture([piper, "--text", text, "--out", out_wav])
            if cp.returncode == 0 and file_ok(out_wav):
                return out_wav
        except Exception as e:
            print("Piper TTS failed:", e)
    cp = run_capture(["espeak-ng","-v","de+f3","-w", out_wav, text])
    return out_wav if cp.returncode == 0 and file_ok(out_wav) else None

# ---------------- Image/text utilities (Pillow textbbox fix) ----------------
def write_centered_text_image(text: str, out_png: str, fontsize: int = 64) -> bool:
    if not PIL_OK or not file_ok(BG_GEN):
        return False
    try:
        im = Image.open(BG_GEN).convert("RGB")
        draw = ImageDraw.Draw(im)
        try:
            font = ImageFont.truetype(FONT_BOLD, fontsize)
        except Exception:
            font = None
        # use textbbox for modern Pillow
        if font:
            bbox = draw.textbbox((0,0), text, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
        else:
            # fallback approximate size
            w = int(len(text) * fontsize * 0.45)
            h = fontsize
        draw.text(((WIDTH - w) / 2, (HEIGHT - h) / 2), text, font=font, fill=(255,255,255))
        im.save(out_png)
        return True
    except Exception as e:
        print("write_centered_text_image failed:", e)
        return False

# ---------------- ffmpeg clip creators ----------------
def make_static_text_clip(text: str, duration: float, out_mp4: str, fontsize: int = 64) -> bool:
    tmp_png = f"{out_mp4}.png"
    ok = write_centered_text_image(text, tmp_png, fontsize=fontsize)
    if not ok:
        if not file_ok(BG_GEN):
            print("Background missing; cannot create clip:", out_mp4)
            return False
        tmp_png = BG_GEN
    vf = f"scale={WIDTH}:{HEIGHT},format=yuv420p,fade=t=in:st=0:d=0.25,fade=t=out:st={max(0.01,duration-0.25)}:d=0.25"
    cp = run_capture(["ffmpeg","-y","-loop","1","-i", tmp_png, "-t", str(duration), "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", out_mp4])
    return cp.returncode == 0 and file_ok(out_mp4)

def concat_files(file_list: List[str], out_file: str) -> bool:
    lf = "concat_list.txt"
    with open(lf, "w", encoding="utf-8") as f:
        for p in file_list:
            f.write(f"file '{p}'\n")
    cp = run_capture(["ffmpeg","-y","-f","concat","-safe","0","-i", lf, "-c", "copy", out_file])
    return cp.returncode == 0 and file_ok(out_file)

def finalize_output(merged: str, voices: List[str], music: Optional[str], final_out: str) -> bool:
    inputs = ["-i", merged]
    voice_inputs = [v for v in voices if file_ok(v)]
    for v in voice_inputs:
        inputs += ["-i", v]
    has_music = music and file_ok(music)
    if has_music:
        inputs += ["-i", music]
    # If no music and no voices, just re-encode
    if not has_music and not voice_inputs:
        cp = run_capture(["ffmpeg","-y","-i", merged, "-c:v","libx264","-pix_fmt","yuv420p","-preset","veryfast","-movflags","+faststart", final_out])
        return cp.returncode == 0 and file_ok(final_out)
    # Build filter_complex:
    # inputs: 0 -> merged video, 1..N -> voice audios, N+1 (optional) -> music
    num_voice = len(voice_inputs)
    if num_voice > 0 and has_music:
        # voice amix: [1:a][2:a]...amix=inputs=num_voice -> [vvoices]
        voice_labels = "".join([f"[{i+1}:a]" for i in range(num_voice)])
        music_idx = num_voice + 1
        fc = f"{voice_labels}amix=inputs={num_voice}:duration=longest[vvoices];[{music_idx}:a]volume=0.25[vmusic];[vvoices][vmusic]amix=inputs=2:duration=longest[aout]"
    elif num_voice > 0 and not has_music:
        voice_labels = "".join([f"[{i+1}:a]" for i in range(num_voice)])
        fc = f"{voice_labels}amix=inputs={num_voice}:duration=longest[aout]"
    else:
        # no voice, only music
        fc = f"[1:a]volume=0.25[aout]"
    cmd = ["ffmpeg","-y"] + inputs + ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]", "-c:v","libx264","-pix_fmt","yuv420p","-preset","veryfast","-c:a","aac","-b:a","192k","-movflags","+faststart", final_out]
    cp = run_capture(cmd)
    return cp.returncode == 0 and file_ok(final_out)

# ---------------- Main ----------------
def main():
    print("Start generation...")
    if not make_background():
        print("Failed to create background; abort.")
        sys.exit(1)

    topic = "Allgemeinwissen"
    if GPT4ALL_OK and os.path.isfile(MODEL_PATH):
        try:
            gm = GPT4All(MODEL_PATH)
            t = gm.generate("Nenne ein eingängiges deutsches Thema in einem Wort.", max_tokens=6).strip().splitlines()[0]
            if t:
                topic = t.split()[0]
        except Exception as e:
            print("Topic auto-gen failed:", e)

    questions = generate_questions(topic)
    if not questions or len(questions) != 7:
        print("Question generation failed/invalid; using fallback.")
        questions = fallback_questions(topic)

    parts: List[str] = []
    voice_files: List[str] = []

    # Intro
    intro_text = f"Teste dein Wissen: {topic}"
    if not make_static_text_clip(intro_text, INTRO_DUR, "seg_intro.mp4", fontsize=64):
        print("Intro creation failed.")
    parts.append("seg_intro.mp4")

    # Per-question
    for i, q in enumerate(questions, start=1):
        dif = q.get("difficulty", "easy")
        dur = DISPLAY.get(dif, DISPLAY["easy"])
        cd_name = f"q{i}_count.mp4"
        if not make_static_text_clip("3", COUNT_DUR, cd_name, fontsize=240):
            print("Warning: countdown creation failed for", i)
        parts.append(cd_name)

        qtext = sanitize(q.get("question", "Frage"))
        q_name = f"q{i}_q.mp4"
        if not make_static_text_clip(qtext, 1.8, q_name, fontsize=56):
            print("Warning: question clip creation failed for", i)
        parts.append(q_name)

        opts = q.get("options", [])
        if opts and isinstance(opts, list) and len(opts) >= 1:
            opts_txt = "   ".join([f"{chr(65+idx)}: {o}" for idx, o in enumerate(opts[:4])])
        else:
            opts_txt = "Antworten: A B C D"
        a_name = f"q{i}_a.mp4"
        if not make_static_text_clip(opts_txt, dur, a_name, fontsize=44):
            print("Warning: answers clip failed for", i)
        parts.append(a_name)

        correct = int(q.get("correct", 0)) if isinstance(q.get("correct", 0), int) else 0
        corr_txt = (opts[correct] if opts and len(opts) > correct else str(q.get("answer", "Lösung")))
        rev_name = f"q{i}_rev.mp4"
        if not make_static_text_clip("Richtige Antwort: " + corr_txt, REVEAL_DUR, rev_name, fontsize=56):
            print("Warning: reveal clip failed for", i)
        parts.append(rev_name)

        wav = f"q{i}.wav"
        v = synthesize_voice(qtext, wav)
        if v:
            voice_files.append(v)

    # Pre-concat checks
    missing = [p for p in parts if not file_ok(p)]
    if missing:
        print("ERROR: Missing clip parts; aborting. Missing list:")
        for m in missing:
            print(" -", m)
        sys.exit(1)

    merged = "merged_nosound.mp4"
    if not concat_files(parts, merged):
        print("ERROR: concat failed.")
        sys.exit(1)

    final_name = f"quiz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    final_path = os.path.join(os.getcwd(), final_name)
    if not finalize_output(merged, voice_files, MUSIC_FILE if file_ok(MUSIC_FILE) else None, final_path):
        print("ERROR: finalize failed. Check ffmpeg logs above.")
        sys.exit(1)

    if not file_ok(final_path):
        print("ERROR: final file not found after finalize.")
        sys.exit(1)

    print("Generation finished. Final file:", final_path)
    sys.exit(0)

if __name__ == "__main__":
    main()
