#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_quiz_video.py
Finale Version mit:
 - GPT4All Frage + Titel (offline)
 - simulated 3D dark glossy background (Pillow + FFmpeg)
 - verwendet hochgeladenes Bild als overlay, falls vorhanden:
     /mnt/data/A_2D_digital_graphic_quiz_image_features_a_dark_bl.png
 - Piper TTS integration (wenn lokal vorhanden), sonst fallback auf espeak-ng (weibliche Stimme)
 - Intro-Voice (weiblich) wird in Intro eingebettet
 - 5s sichtbarer Countdown, Antworten erst danach
 - runde/pill Buttons mit "attention-shake"
 - Crossfades, Musikmix, Cleanup
"""

import os
import json
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Optional Pillow usage for background generation
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# ---- Konfiguration ----
MODEL_PATH = "models/ggml-gpt4all-j.bin"    # GPT4All local model (workflow should download)
MUSIC_FILE = "music/track1.mp3"            # Musik (workflow should download)
# Uploaded file path (from conversation). We'll use this as overlay if present:
UPLOADED_BG = "/mnt/data/A_2D_digital_graphic_quiz_image_features_a_dark_bl.png"

# Generated backgrounds will be written here:
GENERATED_BG = "background_generated.png"

# Font (Ubuntu runner default). If not present, script will try to use PIL default font.
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

OUTPUT_PREFIX = "quiz"
TMP_FILES = [
    "scene_intro.mp4","scene_question.mp4","scene_countdown.mp4","scene_answers.mp4","scene_reveal.mp4","merged_nosound.mp4",
    "intro_voice.wav","background_generated.png"
]

# FFmpeg path (assume available on ubuntu-latest)
FFMPEG = "ffmpeg"

# ---------- Helper ----------
def run(cmd, check=True):
    print("RUN:", " ".join(cmd))
    subprocess.run(cmd, check=check)

def file_exists(p):
    return os.path.isfile(p)

def sanitize_filename(s):
    s = s.strip()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'\s+', '_', s)
    return s[:120]

# ---------- 1) Content generation (GPT4All with fallback) ----------
def generate_quiz_question():
    # Try GPT4All; if not available, fallback to local questions
    try:
        from gpt4all import GPT4All
        print("Using GPT4All to generate a quiz question...")
        model = GPT4All(MODEL_PATH)
        prompt = """Erstelle eine kurze, virale Quizfrage auf Deutsch im JSON-Format:
{
  "question": "Fragetext",
  "options": ["A", "B", "C", "D"],
  "correct": 1,
  "votes": [10,20,50,20]
}
Nur das JSON ausgeben. Die Frage soll neugierig machen."""
        out = model.generate(prompt, max_tokens=200).strip()
        # try to extract JSON
        if not out.startswith("{"):
            s = out.find("{")
            e = out.rfind("}")
            if s != -1 and e != -1:
                out = out[s:e+1]
        quiz = json.loads(out)
        return quiz
    except Exception as e:
        print("GPT4All not available or failed:", e)
        # fallback
        fallback = [
            {
                "question": "Was ist der höchste Berg der Erde?",
                "options": ["K2", "Mount Everest", "Kangchenjunga", "Nanga Parbat"],
                "correct": 1,
                "votes": [5,80,10,5]
            },
            {
                "question": "Wer malte die Mona Lisa?",
                "options": ["Picasso", "Da Vinci", "Van Gogh", "Monet"],
                "correct": 1,
                "votes": [5,85,7,3]
            },
            {
                "question": "Welche Farbe entsteht durch Mischen von Rot und Blau?",
                "options": ["Grün", "Lila", "Orange", "Gelb"],
                "correct": 1,
                "votes": [3,88,5,4]
            }
        ]
        q = random.choice(fallback)
        print("Using fallback question:", q["question"])
        return q

def generate_title(question_text=None):
    # Try GPT4All for a catchy title; fallback to heuristic
    try:
        from gpt4all import GPT4All
        print("Generating title with GPT4All...")
        model = GPT4All(MODEL_PATH)
        prompt = "Erzeuge einen kurzen viralen deutschen Videotitel (max 8 Wörter), der neugierig macht, für ein Quiz.\n"
        if question_text:
            prompt += f"Context: Frage = \"{question_text}\"\n"
        prompt += "Antworte nur mit dem Titel (keine Erklärungen)."
        out = model.generate(prompt, max_tokens=50).strip()
        title = out.splitlines()[0].strip().strip('"')
        if title == "":
            raise ValueError("Empty title")
        return title
    except Exception as e:
        print("GPT4All title generation failed:", e)
        if question_text:
            short = question_text
            if len(short) > 50:
                short = short[:47] + "..."
            return f"Rate mit! — {short}"
        return "Kannst du das erraten? 🤔"

# ---------- 2) Background generation (simulated 3D glossy) ----------
def make_glossy_background(question_text, width=1080, height=1920, out_path=GENERATED_BG):
    """
    Fast simulated 3D glossy background:
      - dark gradient
      - radial glossy shapes
      - bloom/blur
      - optional thematic silhouette (simple vector) based on keywords
    """
    if not PIL_AVAILABLE:
        print("Pillow not available — skipping generated background.")
        return False

    print("Generating simulated 3D glossy background...")

    # Base gradient
    base = Image.new("RGB", (width, height), "#0b0b0f")
    draw = ImageDraw.Draw(base)

    # Vertical gradient (dark navy -> almost black)
    for y in range(height):
        # gradient factor
        t = y / height
        r = int(10 + 20 * t)
        g = int(12 + 10 * t)
        b = int(20 + 40 * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Add glossy radial shapes
    def add_gloss(cx, cy, rx, ry, color, alpha):
        layer = Image.new("RGBA", (width, height), (0,0,0,0))
        ld = ImageDraw.Draw(layer)
        bbox = [cx - rx, cy - ry, cx + rx, cy + ry]
        ld.ellipse(bbox, fill=color + (int(255*alpha),))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=rx//2))
        base.paste(Image.alpha_composite(base.convert("RGBA"), layer), (0,0), layer)

    add_gloss(int(width*0.2), int(height*0.2), 380, 300, (30,80,200), 0.18)
    add_gloss(int(width*0.8), int(height*0.35), 460, 360, (180,40,150), 0.12)
    add_gloss(int(width*0.5), int(height*0.6), 520, 420, (60,180,120), 0.06)

    # Add subtle glossy stripe (like a reflective plane)
    stripe = Image.new("RGBA", (width, height), (0,0,0,0))
    sd = ImageDraw.Draw(stripe)
    sd.rectangle([0, int(height*0.45), width, int(height*0.47)], fill=(255,255,255,25))
    stripe = stripe.filter(ImageFilter.GaussianBlur(20))
    base = Image.alpha_composite(base.convert("RGBA"), stripe)

    # If the uploaded image exists, blend it as texture (low opacity) to tie visuals to user's upload
    if file_exists(UPLOADED_BG):
        try:
            overlay = Image.open(UPLOADED_BG).convert("RGBA")
            overlay = overlay.resize((width, height))
            overlay = overlay.filter(ImageFilter.GaussianBlur(6))
            base = Image.alpha_composite(base, overlay.putalpha(60) or overlay)
        except Exception as e:
            print("Could not blend uploaded bg:", e)

    # Add a thematic silhouette based on simple keywords (very small set)
    keywords = question_text.lower()
    silhouette = None
    if "berg" in keywords or "mount" in keywords or "everest" in keywords:
        # mountain-like polygon
        sil = Image.new("RGBA", (width, height), (0,0,0,0))
        sd = ImageDraw.Draw(sil)
        pts = [(1500,1400),(900,700),(650,900),(480,760),(300,1100)]
        sd.polygon([(p[0]//1, p[1]//1) for p in pts], fill=(10,10,10,220))
        silhouette = sil.filter(ImageFilter.GaussianBlur(6))
    elif "tier" in keywords or "elefant" in keywords or "katze" in keywords or "hund" in keywords:
        # circular soft blob representing creature silhouette
        sil = Image.new("RGBA", (width, height), (0,0,0,0))
        sd = ImageDraw.Draw(sil)
        sd.ellipse([width*0.15, height*0.5, width*0.6, height*0.9], fill=(5,5,5,220))
        silhouette = sil.filter(ImageFilter.GaussianBlur(12))
    elif "wer" in keywords or "malte" in keywords or "mona" in keywords:
        # painterly circle
        sil = Image.new("RGBA", (width, height), (0,0,0,0))
        sd = ImageDraw.Draw(sil)
        sd.ellipse([width*0.3, height*0.2, width*0.8, height*0.8], fill=(10,10,10,220))
        silhouette = sil.filter(ImageFilter.GaussianBlur(18))
    # else: no silhouette for abstract topics

    if silhouette:
        base = Image.alpha_composite(base, silhouette)

    # Final blur & contrast (bloom)
    base = base.convert("RGB")
    base = base.filter(ImageFilter.GaussianBlur(radius=1))
    base.save(out_path, quality=92)
    print("Saved generated background to", out_path)
    return True

# ---------- 3) TTS with Piper (preferred) or espeak-ng fallback ----------
def synthesize_intro_voice_piper(text, out_wav="intro_voice.wav"):
    """
    Tries to use a local 'piper' CLI if present.
    Expected CLI pattern: ./piper/piper --model <model> --text "..." --out out.wav
    The workflow SHOULD place a piper binary in ./piper/ or make 'piper' available.
    """
    # Try common piper binary locations
    candidates = ["./piper/piper", "./piper", "piper"]
    for c in candidates:
        if shutil.which(c) or os.path.isfile(c):
            piper_cmd = c
            break
    else:
        piper_cmd = None

    if piper_cmd:
        # Model path for piper voice should be downloaded by the workflow (example: ./piper_models/de_de_eva)
        # We'll attempt a common model folder; if not found, user should ensure model exists.
        candidate_models = ["./piper_models/de_de_eva", "./piper_models/de_eva", "./piper_models/eva", "./piper_models"]
        model_arg = None
        for m in candidate_models:
            if os.path.isdir(m):
                model_arg = m
                break
        # Build command (best-effort; exact flags depend on piper build — adjust in workflow if necessary)
        cmd = []
        if model_arg:
            cmd = [piper_cmd, "--model", model_arg, "--text", text, "--out", out_wav]
        else:
            # Without model path, try default invocation
            cmd = [piper_cmd, "--text", text, "--out", out_wav]
        try:
            print("Trying Piper TTS with command:", " ".join(cmd))
            run(cmd)
            if file_exists(out_wav):
                print("Piper TTS synthesized:", out_wav)
                return True
        except Exception as e:
            print("Piper invocation failed:", e)
    print("Piper not found or failed. Falling back to espeak-ng.")
    return False

def synthesize_intro_voice_espeak(text, out_wav="intro_voice.wav"):
    """
    Use espeak-ng as fallback with a female voice variant (de+f3 or similar).
    espeak-ng must be installed in the runner; ubuntu-latest usually has espeak.
    """
    # try various voices; choose a female german voice if available
    voice = "de+f3"
    cmd = ["espeak", "-v", voice, "-w", out_wav, text]
    try:
        print("Synthesizing with espeak-ng:", " ".join(cmd))
        run(cmd)
        if file_exists(out_wav):
            print("espeak produced:", out_wav)
            return True
    except Exception as e:
        print("espeak failed:", e)
    # fallback: try simple espeak without voice flag
    try:
        run(["espeak", "-w", out_wav, text])
        return file_exists(out_wav)
    except Exception:
        return False

def synthesize_intro_voice(text, out_wav="intro_voice.wav"):
    # Priority: Piper -> espeak
    ok = synthesize_intro_voice_piper(text, out_wav=out_wav)
    if ok:
        return out_wav
    ok2 = synthesize_intro_voice_espeak(text, out_wav=out_wav)
    if ok2:
        return out_wav
    print("No TTS available. Skipping voice generation.")
    return None

# ---------- 4) Scene creation (FFmpeg calls) ----------
def draw_text_file_filter(fontfile, textfile, fontsize, y_expr="(h-text_h)/2", box=1):
    # returns drawtext filter using textfile
    return f"drawtext=fontfile={fontfile}:textfile={textfile}:fontcolor=white:fontsize={fontsize}:box={box}:boxcolor=black@0.35:boxborderw=12:x=(w-text_w)/2:y={y_expr}"

def create_scene_intro(title_text, voice_wav=None, duration=2):
    # write title and subtitle files
    with open("title_intro.txt", "w", encoding="utf-8") as f:
        f.write(title_text)
    with open("subtitle_intro.txt", "w", encoding="utf-8") as f:
        f.write("Antworte schnell! (5s)")

    vf = draw_text_file_filter(FONT_PATH, "title_intro.txt", 64, y_expr="320") + "," \
         + draw_text_file_filter(FONT_PATH, "subtitle_intro.txt", 30, y_expr="420") \
         + f",fade=t=in:st=0:d=0.45,fade=t=out:st={duration-0.45}:d=0.45"

    # If voice_wav available: include as audio track for the intro
    if voice_wav and file_exists(voice_wav):
        # Create video with audio mapped
        cmd = [
            FFMPEG, "-y",
            "-loop", "1", "-i", GENERATED_BG,
            "-i", voice_wav,
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", "scene_intro.mp4"
        ]
    else:
        cmd = [
            FFMPEG, "-y",
            "-loop", "1", "-i", GENERATED_BG,
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "scene_intro.mp4"
        ]
    run(cmd)

def create_scene_question(quiz, duration=4):
    with open("question_display.txt", "w", encoding="utf-8") as f:
        f.write(quiz["question"])
    with open("question_header.txt", "w", encoding="utf-8") as f:
        f.write("Rate jetzt!")

    vf = draw_text_file_filter(FONT_PATH, "question_header.txt", 34, y_expr="220") + "," \
         + draw_text_file_filter(FONT_PATH, "question_display.txt", 72, y_expr="360") \
         + f",fade=t=in:st=0:d=0.45,fade=t=out:st={duration-0.45}:d=0.45"

    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-i", GENERATED_BG,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "scene_question.mp4"
    ]
    run(cmd)

def create_scene_countdown(count=5, duration=5):
    # large central countdown: use expression eif:5-t:d to show integer seconds
    vf_count = f"drawtext=fontfile={FONT_PATH}:text='%{{eif\\:{count}-t\\:d}}':fontcolor=white:fontsize=220:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.45:boxborderw=16"
    vf = vf_count + f",fade=t=in:st=0:d=0.35,fade=t=out:st={duration-0.35}:d=0.35"
    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-i", GENERATED_BG,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "scene_countdown.mp4"
    ]
    run(cmd)

def create_scene_answers(quiz, duration=5):
    # Pill-like buttons with strong horizontal shake: x = (w-text_w)/2 + 15*sin(30*t)
    options = quiz["options"]
    ys = [700, 840, 980, 1120]  # tuned for 1080x1920
    fontsize = 56
    vf_parts = []
    glow_parts = []
    # glow behind (bigger, low opacity) to imitate neon glow
    for i, opt in enumerate(options):
        letter = chr(65+i)
        text = f"{letter}) {opt}"
        t_esc = text.replace(":", "\\:").replace("'", "\\'")
        glow = f"drawtext=fontfile={FONT_PATH}:text='{t_esc}':fontsize={fontsize+6}:fontcolor=white@0.12:x='(w-text_w)/2 + 15*sin(30*t)':y={ys[i]}"
        main = f"drawtext=fontfile={FONT_PATH}:text='{t_esc}':fontsize={fontsize}:fontcolor=white:borderw=3:shadowx=2:shadowy=2:x='(w-text_w)/2 + 15*sin(30*t)':y={ys[i]}:box=1:boxcolor=white@0.06:boxborderw=36"
        glow_parts.append(glow)
        vf_parts.append(main)
    vf = ",".join(glow_parts + vf_parts) + f",fade=t=in:st=0:d=0.45,fade=t=out:st={duration-0.45}:d=0.45"
    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-i", GENERATED_BG,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "scene_answers.mp4"
    ]
    run(cmd)

def create_scene_reveal(quiz, duration=4):
    correct = quiz["correct"]
    correct_text = quiz["options"][correct]
    votes = quiz.get("votes", [])
    reveal = f"Richtige Antwort: {correct_text}"
    votes_line = ""
    if votes and len(votes) >= len(quiz["options"]):
        votes_line = "   ".join([f"{chr(65+i)}: {votes[i]}%" for i in range(len(votes))])
    with open("reveal_main.txt", "w", encoding="utf-8") as f:
        f.write(reveal)
    with open("reveal_votes.txt", "w", encoding="utf-8") as f:
        f.write(votes_line)
    vf = draw_text_file_filter(FONT_PATH, "reveal_main.txt", 68, y_expr="880") + "," \
         + draw_text_file_filter(FONT_PATH, "reveal_votes.txt", 40, y_expr="980") \
         + f",fade=t=in:st=0:d=0.45,fade=t=out:st={duration-0.45}:d=0.45"
    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-i", GENERATED_BG,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "scene_reveal.mp4"
    ]
    run(cmd)

# ---------- 5) Merge scenes (crossfade chain) ----------
def merge_scenes_with_crossfade(durations=[2,4,5,5,4], output_video="merged_nosound.mp4"):
    inputs = ["scene_intro.mp4","scene_question.mp4","scene_countdown.mp4","scene_answers.mp4","scene_reveal.mp4"]
    cmd = [FFMPEG, "-y"]
    for inp in inputs:
        cmd += ["-i", inp]
    cross_dur = 0.7
    # offsets: cumulative durations minus half cross dur
    offsets = []
    cum = 0.0
    for d in durations[:-1]:
        cum += d
        offsets.append(max(0.1, cum - (cross_dur/2)))
    fc_parts = []
    for i in range(len(inputs)-1):
        a = "[{}:v]".format(i) if i == 0 else "[v{}]".format(i)
        b = "[{}:v]".format(i+1)
        out_label = "[v{}]".format(i+1)
        fc_parts.append(f"{a}{b}xfade=transition=fade:duration={cross_dur}:offset={offsets[i]}{out_label};")
    filter_complex = "".join(fc_parts)
    final_label = f"[v{len(inputs)-1}]"
    cmd += ["-filter_complex", filter_complex, "-map", final_label, "-c:v", "libx264", "-crf", "23", "-preset", "veryfast", output_video]
    run(cmd)

# ---------- 6) Add music & finalize ----------
def add_music_and_export(input_video, music_file, output_file):
    if not file_exists(music_file):
        # If no music, just rename / copy
        print("No music file found; copying video as final output.")
        shutil.copyfile(input_video, output_file)
        return
    # Attach music as audio track, reduced volume
    cmd = [
        FFMPEG, "-y",
        "-i", input_video,
        "-i", music_file,
        "-c:v", "copy",
        "-map", "0:v",
        "-map", "1:a",
        "-filter_complex", "[1:a]volume=0.25[aout]",
        "-map", "[aout]",
        "-shortest",
        output_file
    ]
    try:
        run(cmd)
    except Exception as e:
        print("Primary music mix failed, fallback to simpler mapping:", e)
        cmd2 = [
            FFMPEG, "-y",
            "-i", input_video,
            "-i", music_file,
            "-c:v", "copy",
            "-map", "0:v",
            "-map", "1:a",
            "-shortest",
            output_file
        ]
        run(cmd2)

# ---------- 7) Cleanup ----------
def cleanup_temp():
    for f in TMP_FILES + ["title_intro.txt","subtitle_intro.txt","question_display.txt","question_header.txt","reveal_main.txt","reveal_votes.txt"]:
        try:
            if os.path.exists(f):
                os.remove(f)
        except Exception as e:
            print("Cleanup error:", e)

# ---------- Main flow ----------
def main():
    print("Starting quiz video generation...")
    quiz = generate_quiz_question()
    title = generate_title(quiz.get("question"))
    print("Title:", title)
    # 1) generate or use background
    bg_ok = False
    # prefer generated glossy background (fast)
    if PIL_AVAILABLE:
        try:
            bg_ok = make_glossy_background(quiz.get("question", ""), out_path=GENERATED_BG)
        except Exception as e:
            print("Background generation error:", e)
            bg_ok = False
    # if generation failed but uploaded image exists, use uploaded image as background (copied/renamed)
    if not bg_ok:
        if file_exists(UPLOADED_BG):
            print("Using uploaded background image as fallback.")
            shutil.copyfile(UPLOADED_BG, GENERATED_BG)
            bg_ok = True
    if not bg_ok:
        print("No background available. Creating a simple dark PNG placeholder.")
        # create a very simple placeholder with Pillow if available, else create via FFmpeg color
        if PIL_AVAILABLE:
            img = Image.new("RGB", (1080,1920), (15,15,30))
            img.save(GENERATED_BG)
            bg_ok = True
        else:
            # create via ffmpeg color source
            run([FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=#0f0f1e:s=1080x1920:d=0.5", "-frames:v", "1", GENERATED_BG])

    # 2) synthesize intro voice
    intro_text = title + ". " + quiz.get("question", "")
    intro_wav = synthesize_intro_voice(intro_text, out_wav="intro_voice.wav")

    # 3) create scenes
    create_scene_intro(title, voice_wav=intro_wav, duration=2)
    create_scene_question(quiz, duration=4)
    create_scene_countdown(count=5, duration=5)
    create_scene_answers(quiz, duration=5)
    create_scene_reveal(quiz, duration=4)

    # 4) merge scenes
    durations = [2,4,5,5,4]
    merge_scenes_with_crossfade(durations=durations, output_video="merged_nosound.mp4")

    # 5) final file name with title sanitized
    safe_title = sanitize_filename(title)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outname = f"{OUTPUT_PREFIX}_{safe_title}_{ts}.mp4"

    # 6) add music and export
    add_music_and_export("merged_nosound.mp4", MUSIC_FILE, outname)

    print("✅ Finished. Output file:", outname)
    cleanup_temp()

if __name__ == "__main__":
    main()
