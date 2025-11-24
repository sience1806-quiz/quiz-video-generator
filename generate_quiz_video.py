#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_quiz_video_pro.py
Professional quiz video generator for TikTok/Shorts (1080x1920) with:
 - animated question + answer UI (MoviePy)
 - TTS per question (Piper preferred, else espeak-ng)
 - GPT4All for high-quality dynamic questions (fallback implemented)
 - Final output: quiz_YYYYMMDD_HHMMSS.mp4 (H.264, yuv420p, AAC)
 - Robust logging and fallbacks for CI (GitHub Actions)
 
Notes:
 - Recommended to add "pip install moviepy" to your workflow dependencies.
 - If MoviePy is missing, script falls back to a safe ffmpeg-based pipeline.
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

# Try to import MoviePy and Pillow; set flags and provide fallbacks
try:
    from moviepy.editor import (
        ColorClip, ImageClip, TextClip, CompositeVideoClip, AudioFileClip,
        concatenate_videoclips, VideoClip, CompositeAudioClip
    )
    MOVIEPY_OK = True
except Exception:
    MOVIEPY_OK = False

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
BG_GEN = "bg_generated.png"

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Durations
INTRO_DUR = 2.0
COUNT_DUR = 2.5
DISPLAY_EASY = 2.8
DISPLAY_MED = 3.2
DISPLAY_HARD = 3.8
DISPLAY_IMP = 4.0
REVEAL_DUR = 1.6

DIFFICULTY_SEQUENCE = ["easy","easy","easy","medium","medium","hard","impossible"]
PIPER_CANDIDATES = ["./piper/piper", "./piper", "piper"]
PIPER_MODEL_DIRS = ["./piper_models/de_DE-eva_k-x_low", "./piper_models/de_de_eva", "./piper_models"]

# visual constants
BG_COLOR = (15, 15, 30)  # fallback color

# ---------------- Helpers ----------------
def log(msg: str):
    print(msg, flush=True)

def run_capture(cmd: List[str]) -> subprocess.CompletedProcess:
    log("RUN: " + " ".join(cmd))
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True)
        if cp.returncode != 0:
            log(f"Command failed (rc={cp.returncode}): {' '.join(cmd)}")
            if cp.stdout:
                log("--- stdout ---")
                log(cp.stdout)
            if cp.stderr:
                log("--- stderr ---")
                log(cp.stderr)
        return cp
    except Exception as e:
        log("Exception running command: " + str(e))
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=str(e))

def file_ok(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0

def sanitize(s: str) -> str:
    return "".join(ch for ch in s if ord(ch) >= 32).strip()

# ---------------- Background generation (small moving gradient via MoviePy) ----------------
def ensure_background():
    # If an uploaded BG exists, use it
    if os.path.isfile(UPLOADED_BG):
        shutil.copyfile(UPLOADED_BG, BG_GEN)
        return True
    # else create a basic gradient PNG (Pillow if available)
    if PIL_OK:
        try:
            img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
            draw = ImageDraw.Draw(img)
            for y in range(HEIGHT):
                t = y / HEIGHT
                r = int(10 + 25 * t)
                g = int(10 + 15 * t)
                b = int(25 + 60 * t)
                draw.line([(0,y),(WIDTH,y)], fill=(r,g,b))
            img.save(BG_GEN, quality=92)
            return True
        except Exception as e:
            log("Pillow background creation failed: " + str(e))
    # fallback using ffmpeg to create a single-color PNG
    cp = run_capture(["ffmpeg","-y","-f","lavfi","-i",f"color=c=#0f0f1e:s={WIDTH}x{HEIGHT}:d=0.1","-frames:v","1",BG_GEN])
    return file_ok(BG_GEN)

# ---------------- GPT4All question generation (improved prompt) ----------------
def make_votes_for(correct_index: int) -> List[int]:
    base = [random.uniform(5,25) for _ in range(4)]
    base[correct_index] += random.uniform(20,40)
    s = sum(base)
    perc = [int(round(x/s*100)) for x in base]
    diff = 100 - sum(perc)
    if diff != 0:
        perc[correct_index] += diff
    return perc

def parse_json_out(s: str):
    if not s: return None
    if "[" in s and "]" in s:
        s = s[s.find("["):s.rfind("]")+1]
    try:
        j = json.loads(s)
        if isinstance(j, list):
            return j
    except Exception as e:
        log("JSON parse error from GPT output: " + str(e))
    return None

def generate_questions(topic: str="Allgemeinwissen") -> List[Dict]:
    # Try GPT4All
    if GPT4ALL_OK and os.path.isfile(MODEL_PATH):
        try:
            model = GPT4All(MODEL_PATH)
            prompt = f"""
Erstelle exakt 7 hochwertige Quizfragen auf Deutsch zum Thema "{topic}".
Gib nur ein reines JSON-Array zurück mit Objekten:
{{ "difficulty":"easy|medium|hard|impossible",
  "question":"Frage in einem Satz",
  "options":["A","B","C","D"],
  "correct":0-3
}}
Die Reihenfolge soll 3 easy, 2 medium, 1 hard, 1 impossible sein.
Stelle sicher, dass Optionen plausibel sind und die richtige Antwort plausibel ersichtlich ist.
"""
            out = model.generate(prompt, max_tokens=800).strip()
            parsed = parse_json_out(out)
            if parsed and len(parsed) == 7:
                # normalize
                for item in parsed:
                    if "options" not in item or not isinstance(item["options"], list) or len(item["options"]) != 4:
                        item["options"] = ["A","B","C","D"]
                    if "correct" not in item:
                        item["correct"] = 0
                    if "votes" not in item:
                        item["votes"] = make_votes_for(item["correct"])
                return parsed
            else:
                log("GPT output not valid JSON array of length 7, falling back.")
        except Exception as e:
            log("GPT4All generation failed: " + str(e))
    # Fallback high-quality generator (templated but varied)
    seq = DIFFICULTY_SEQUENCE
    out = []
    # some pools for better variety
    easy_pool = [
        ("Wie viele Kontinente gibt es auf der Erde?", ["5","6","7","8"], 2),
        ("Welche Farbe hat der reife Himmel an einem klaren Tag?", ["Grün","Blau","Rot","Gelb"], 1),
        ("Welches Tier ist für Honigproduktion bekannt?", ["Käfer","Biene","Spinne","Fisch"], 1)
    ]
    medium_pool = [
        ("In welchem Jahr landete die erste bemannte Mission auf dem Mond?", ["1959","1969","1979","1989"], 1),
        ("Was ist die Hauptstadt von Australien?", ["Sydney","Melbourne","Canberra","Brisbane"], 2)
    ]
    hard_pool = [
        ("Welches Element hat das chemische Symbol 'Ag'?", ["Gold","Silber","Argon","Aluminium"], 1)
    ]
    imposs_pool = [
        ("Wie lautet die Lichtgeschwindigkeit in m/s (ungefähr)?", ["3e6","3e7","3e8","3e9"], 2)
    ]
    # fill according to sequence with random picks
    for dif in seq:
        if dif == "easy":
            q, opts, corr = random.choice(easy_pool)
        elif dif == "medium":
            q, opts, corr = random.choice(medium_pool)
        elif dif == "hard":
            q, opts, corr = random.choice(hard_pool)
        else:
            q, opts, corr = random.choice(imposs_pool)
        out.append({"difficulty": dif, "question": q, "options": opts, "correct": corr, "votes": make_votes_for(corr)})
    return out

# ---------------- TTS: Piper (preferred) or espeak-ng fallback ----------------
def find_piper():
    for c in PIPER_CANDIDATES:
        if shutil.which(c) or os.path.isfile(c):
            return c
    return None

def synthesize_with_piper(text: str, out_wav: str) -> bool:
    piper = find_piper()
    if not piper:
        return False
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
        return cp.returncode == 0 and file_ok(out_wav)
    except Exception as e:
        log("Piper TTS failed: " + str(e))
        return False

def synthesize_with_espeak(text: str, out_wav: str) -> bool:
    try:
        cp = run_capture(["espeak-ng","-v","de+f3","-w", out_wav, text])
        return cp.returncode == 0 and file_ok(out_wav)
    except Exception as e:
        log("espeak-ng failed: " + str(e))
        return False

def synthesize_voice(text: str, out_wav: str) -> Optional[str]:
    text = sanitize(text)
    ok = synthesize_with_piper(text, out_wav)
    if ok:
        return out_wav
    ok2 = synthesize_with_espeak(text, out_wav)
    if ok2:
        return out_wav
    return None

# ---------------- MoviePy animation building ----------------
def build_moviepy_video(questions: List[Dict], music_file: Optional[str]) -> Optional[str]:
    if not MOVIEPY_OK:
        log("MoviePy not available — cannot build advanced animations.")
        return None
    log("Building MoviePy animated video...")
    clips = []
    # moving background: use ImageClip of BG_GEN and a slight zoom/pan effect via lambda
    bg_clip = ImageClip(BG_GEN).set_duration(0.01)  # placeholder
    # We'll create per-segment composite clips with background as base
    def make_center_text_clip(text, duration, fontsize=72, color='white', pos=('center','center')):
        txt = TextClip(text, fontsize=fontsize, font='DejaVu-Sans-Bold' if os.path.exists(FONT_PATH) else None,
                       color=color, size=(WIDTH*9//10, None), method='caption')
        txt = txt.set_duration(duration)
        # animate: fade in + slight pop
        txt = txt.crossfadein(0.18)
        return txt
    # Intro
    intro_txt = make_center_text_clip("Teste dein Wissen!", INTRO_DUR, fontsize=84)
    intro_bg = ImageClip(BG_GEN).set_duration(INTRO_DUR)
    intro = CompositeVideoClip([intro_bg, intro_txt.set_position('center')], size=(WIDTH,HEIGHT)).set_fps(FPS)
    clips.append(intro)
    # For each question: countdown, question, answers, reveal
    for idx, q in enumerate(questions, start=1):
        # Countdown: 3 -> using simple TextClip animations
        cd_txt = TextClip("3", fontsize=260, color='white', font='DejaVu-Sans-Bold' if os.path.exists(FONT_PATH) else None)
        cd_txt = cd_txt.set_duration(0.6).crossfadein(0.05).crossfadeout(0.05)
        cd_bg = ImageClip(BG_GEN).set_duration(cd_txt.duration)
        clips.append(CompositeVideoClip([cd_bg, cd_txt.set_position('center')], size=(WIDTH,HEIGHT)).set_fps(FPS))
        # Question clip
        q_text = sanitize(q.get("question","Frage"))
        q_dur = 1.8
        q_clip_bg = ImageClip(BG_GEN).set_duration(q_dur)
        q_txt = TextClip(q_text, fontsize=64, color='white', size=(WIDTH*9//10, None), method='caption').set_duration(q_dur)
        # add TTS starting slightly after visual start
        wav = f"q{idx}_tts.wav"
        aud = None
        vpath = synthesize_voice(q_text, wav)
        if vpath:
            try:
                aud = AudioFileClip(vpath)
            except Exception as e:
                log("Failed to load question audio: " + str(e))
                aud = None
        comp_q = CompositeVideoClip([q_clip_bg, q_txt.set_position(('center', HEIGHT*0.28))], size=(WIDTH,HEIGHT)).set_duration(q_dur)
        if aud:
            # align audio start a bit earlier so it's in sync
            comp_q = comp_q.set_audio(aud.set_start(0.05))
        clips.append(comp_q.set_fps(FPS))
        # Answers block: animate 4 pills one after another (concise)
        opts = q.get("options", ["A","B","C","D"])
        ans_dur = DISPLAY_EASY if q.get("difficulty","easy")=="easy" else (DISPLAY_MED if q.get("difficulty","easy")=="medium" else (DISPLAY_HARD if q.get("difficulty","easy")=="hard" else DISPLAY_IMP))
        # For space reasons we create a single text with answers horizontally or stacked
        ans_text = "   ".join([f"{chr(65+i)}: {o}" for i,o in enumerate(opts[:4])])
        ans_clip_bg = ImageClip(BG_GEN).set_duration(ans_dur)
        ans_txt = TextClip(ans_text, fontsize=48, color='white', size=(WIDTH*9//10, None), method='caption').set_duration(ans_dur)
        clips.append(CompositeVideoClip([ans_clip_bg, ans_txt.set_position(('center', HEIGHT*0.55))], size=(WIDTH,HEIGHT)).set_fps(FPS))
        # Reveal
        correct_idx = int(q.get("correct",0))
        correct_text = opts[correct_idx] if opts and len(opts) > correct_idx else str(q.get("answer","Lösung"))
        rev_text = f"Richtige Antwort: {chr(65+correct_idx)} — {correct_text}"
        rev_bg = ImageClip(BG_GEN).set_duration(REVEAL_DUR)
        rev_txt = TextClip(rev_text, fontsize=66, color='white', size=(WIDTH*9//10, None), method='caption').set_duration(REVEAL_DUR)
        clips.append(CompositeVideoClip([rev_bg, rev_txt.set_position(('center', HEIGHT*0.45))], size=(WIDTH,HEIGHT)).set_fps(FPS))
    # Concatenate all clips
    final = concatenate_videoclips(clips, method='compose')
    # Add background music if present
    if music_file and file_ok(music_file):
        try:
            music = AudioFileClip(music_file).volumex(0.15)
            # build audio: if there is separate TTS audios they are already attached to question clips.
            # Compose with video audio where present: moviepy will mix them if we use CompositeAudioClip
            # Collect all existing audio tracks from clips
            audio_tracks = []
            for c in clips:
                if c.audio is not None:
                    audio_tracks.append(c.audio)
            audio_tracks.append(music)
            final_audio = CompositeAudioClip(audio_tracks)
            final = final.set_audio(final_audio)
        except Exception as e:
            log("Music attach failed: " + str(e))
    # Write output
    outname = os.path.join(os.getcwd(), f"quiz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
    log("Writing final video to " + outname + " (this may take a while)...")
    try:
        # use codec libx264 for compatibility
        final.write_videofile(outname, codec="libx264", audio_codec="aac", fps=FPS, threads=2, preset="medium", ffmpeg_params=["-pix_fmt","yuv420p"])
        return outname
    except Exception as e:
        log("Failed to write final video via MoviePy: " + str(e))
        return None

# ---------------- Fallback: ffmpeg static pipeline (simpler, stable) ----------------
def fallback_pipeline(questions: List[Dict]) -> Optional[str]:
    log("Running fallback ffmpeg pipeline (static text images)...")
    # This uses the earlier simpler approach: create static text PNGs and render short mp4s via ffmpeg, concat, mix
    # Reuse functions: write centered text images with Pillow if available, else use color background
    def write_centered_png(text, outpng, fontsize=64):
        if PIL_OK and file_ok(BG_GEN):
            try:
                im = Image.open(BG_GEN).convert("RGB")
                d = ImageDraw.Draw(im)
                try:
                    font = ImageFont.truetype(FONT_PATH, fontsize)
                except Exception:
                    font = None
                if font:
                    bbox = d.textbbox((0,0), text, font=font)
                    w = bbox[2]-bbox[0]; h = bbox[3]-bbox[1]
                else:
                    w = int(len(text)*fontsize*0.45); h = fontsize
                d.text(((WIDTH-w)/2,(HEIGHT-h)/2), text, font=font, fill=(255,255,255))
                im.save(outpng)
                return True
            except Exception as e:
                log("PNG write failed: " + str(e))
                return False
        # fallback: use a single-color fill created earlier
        return False
    parts = []
    # intro
    intro_img = "intro.png"
    write_centered_png("Teste dein Wissen!", intro_img, fontsize=84)
    run_capture(["ffmpeg","-y","-loop","1","-i", intro_img if file_ok(intro_img) else BG_GEN, "-t", str(INTRO_DUR),
                 "-vf", f"scale={WIDTH}:{HEIGHT},format=yuv420p,fade=t=in:st=0:d=0.25,fade=t=out:st={max(0.01,INTRO_DUR-0.25)}:d=0.25",
                 "-c:v","libx264","-pix_fmt","yuv420p","intro.mp4"])
    parts.append("intro.mp4")
    # per question
    for i,q in enumerate(questions, start=1):
        qtext = sanitize(q.get("question","Frage"))
        opts = q.get("options", ["A","B","C","D"])
        # countdown
        run_capture(["ffmpeg","-y","-loop","1","-i", BG_GEN, "-t", str(COUNT_DUR), "-vf", f"scale={WIDTH}:{HEIGHT}", "-c:v","libx264","-pix_fmt","yuv420p", f"q{i}_count.mp4"])
        parts.append(f"q{i}_count.mp4")
        # question
        run_capture(["ffmpeg","-y","-loop","1","-i", BG_GEN, "-t", "1.8", "-vf", f"drawtext=fontfile={FONT_PATH}:text='{qtext}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/3", "-c:v","libx264","-pix_fmt","yuv420p", f"q{i}_q.mp4"])
        parts.append(f"q{i}_q.mp4")
        opts_txt = "   ".join([f"{chr(65+idx)}: {o}" for idx,o in enumerate(opts[:4])])
        dur = DISPLAY_EASY if q.get("difficulty","easy")=="easy" else (DISPLAY_MED if q.get("difficulty","easy")=="medium" else (DISPLAY_HARD if q.get("difficulty","easy")=="hard" else DISPLAY_IMP))
        run_capture(["ffmpeg","-y","-loop","1","-i", BG_GEN, "-t", str(dur), "-vf", f"drawtext=fontfile={FONT_PATH}:text='{opts_txt}':fontcolor=white:fontsize=40:x=(w-text_w)/2:y=h*0.55", "-c:v","libx264","-pix_fmt","yuv420p", f"q{i}_a.mp4"])
        parts.append(f"q{i}_a.mp4")
        correct_idx = int(q.get("correct",0))
        corr_txt = opts[correct_idx] if len(opts)>correct_idx else str(q.get("answer","Lösung"))
        run_capture(["ffmpeg","-y","-loop","1","-i", BG_GEN, "-t", str(REVEAL_DUR), "-vf", f"drawtext=fontfile={FONT_PATH}:text='Richtige Antwort: {corr_txt}':fontcolor=white:fontsize=56:x=(w-text_w)/2:y=h*0.5", "-c:v","libx264","-pix_fmt","yuv420p", f"q{i}_rev.mp4"])
        parts.append(f"q{i}_rev.mp4")
        # tts
        wav = f"q{i}.wav"
        synthesize_voice(qtext, wav)
    # concat
    with open("concat_list.txt","w",encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    cp = run_capture(["ffmpeg","-y","-f","concat","-safe","0","-i","concat_list.txt","-c","copy","merged.mp4"])
    if cp.returncode != 0:
        return None
    # mix voices & music (fixed mixing)
    voice_files = [f"q{i}.wav" for i in range(1, len(questions)+1) if file_ok(f"q{i}.wav")]
    # build inputs list
    inputs = ["-i", "merged.mp4"]
    for v in voice_files:
        inputs += ["-i", v]
    if file_ok(MUSIC_FILE):
        inputs += ["-i", MUSIC_FILE]
    # build filter_complex similar to finalize_output
    num_voice = len(voice_files)
    has_music = file_ok(MUSIC_FILE)
    if num_voice > 0 and has_music:
        voice_labels = "".join([f"[{i+1}:a]" for i in range(num_voice)])
        music_idx = num_voice + 1
        fc = f"{voice_labels}amix=inputs={num_voice}:duration=longest[vvoices];[{music_idx}:a]volume=0.2[vmusic];[vvoices][vmusic]amix=inputs=2:duration=longest[aout]"
    elif num_voice > 0 and not has_music:
        voice_labels = "".join([f"[{i+1}:a]" for i in range(num_voice)])
        fc = f"{voice_labels}amix=inputs={num_voice}:duration=longest[aout]"
    else:
        fc = "[1:a]volume=0.2[aout]" if has_music else ""
    cmd = ["ffmpeg","-y"] + inputs + (["-filter_complex", fc, "-map","0:v","-map","[aout]","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","final.mp4"] if fc else ["-i","/dev/null","-c:v","libx264","-pix_fmt","yuv420p","final.mp4"])
    cp = run_capture(cmd)
    if cp.returncode != 0:
        return None
    final_name = os.path.join(os.getcwd(), f"quiz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
    shutil.move("final.mp4", final_name)
    return final_name

# ---------------- Main flow ----------------
def main():
    log("Starting pro quiz video generation...")
    if not ensure_background():
        log("Background creation failed. Aborting.")
        sys.exit(1)
    # choose topic
    topic = "Allgemeinwissen"
    if GPT4ALL_OK and os.path.isfile(MODEL_PATH):
        try:
            gm = GPT4All(MODEL_PATH)
            t = gm.generate("Nenne ein kurzes deutsches Thema in einem Wort.", max_tokens=6).strip().splitlines()[0]
            if t:
                topic = t.split()[0]
        except Exception as e:
            log("Topic auto-gen failed: " + str(e))
    questions = generate_questions(topic)
    if not questions or len(questions) != 7:
        log("Question generation failed/fallback used.")
        questions = generate_questions(topic)
    # Build video - try moviepy first
    out = None
    if MOVIEPY_OK:
        try:
            out = build_moviepy_video(questions, MUSIC_FILE if file_ok(MUSIC_FILE) else None)
        except Exception as e:
            log("MoviePy build failed: " + str(e))
            out = None
    if not out:
        out = fallback_pipeline(questions)
    if not out or not file_ok(out):
        log("Failed to produce final video.")
        sys.exit(1)
    log("Final video produced: " + out)
    sys.exit(0)

if __name__ == "__main__":
    main()
