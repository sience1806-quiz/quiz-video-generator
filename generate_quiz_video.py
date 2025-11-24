#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_quiz_video_pro_short.py
Creates a polished 9:16 quiz video with 5 AI-generated questions.
- MoviePy animations when available (recommended)
- TTS per question (Piper preferred, else espeak-ng)
- Question source priority: OpenAI API -> GPT4All -> internal fallback
- Output: quiz_YYYYMMDD_HHMMSS.mp4 in CWD
"""
from __future__ import annotations
import os, sys, json, random, shutil, subprocess
from datetime import datetime
from typing import List, Dict, Optional

# Try imports
try:
    from moviepy.editor import (
        ColorClip, ImageClip, TextClip, CompositeVideoClip,
        concatenate_videoclips, AudioFileClip, CompositeAudioClip
    )
    MOVIEPY = True
except Exception:
    MOVIEPY = False

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    PIL_OK = True
except Exception:
    PIL_OK = False

# Optional: OpenAI client
OPENAI_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_APIKEY")
USE_OPENAI = bool(OPENAI_KEY)
if USE_OPENAI:
    try:
        import openai
        openai.api_key = OPENAI_KEY
    except Exception:
        USE_OPENAI = False

# Optional GPT4All (local)
try:
    from gpt4all import GPT4All
    GPT4ALL_OK = True
except Exception:
    GPT4ALL_OK = False

# Config
WIDTH, HEIGHT = 1080, 1920
FPS = 30
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BG_UP = "/mnt/data/A_2D_digital_graphic_quiz_image_features_a_dark_bl.png"
BG_GEN = "bg_quiz.png"
MUSIC = "music/track1.mp3"
PIPER_CANDS = ["./piper/piper","./piper","piper"]
PIPER_MODEL_DIRS = ["./piper_models/de_DE-eva_k-x_low", "./piper_models"]

# Durations (short & snappy)
INTRO_DUR = 1.8
COUNT_DUR = 1.0   # fast numeric pop
QUESTION_VIS = 1.8
ANS_EASY = 2.5
ANS_MED = 3.0
ANS_HARD = 3.8
REVEAL_DUR = 1.5

NUM_QUESTIONS = 5  # as requested (option A)

# Helpers
def log(*a, **k): print(*a, **k); sys.stdout.flush()
def file_ok(p): return os.path.exists(p) and os.path.getsize(p)>0
def sanitize(s): return "".join(ch for ch in s if ord(ch)>=32)

# Background generation (Pillow if available)
def ensure_background():
    if os.path.isfile(BG_UP):
        shutil.copyfile(BG_UP, BG_GEN)
        return True
    if PIL_OK:
        try:
            img = Image.new("RGB", (WIDTH, HEIGHT), (12,12,20))
            d = ImageDraw.Draw(img)
            for y in range(HEIGHT):
                t = y/HEIGHT
                r = int(8 + 20*t); g = int(10 + 10*t); b = int(18 + 40*t)
                d.line([(0,y),(WIDTH,y)], fill=(r,g,b))
            img.save(BG_GEN, quality=92)
            return True
        except Exception as e:
            log("BG Pillow fail:", e)
    # fallback via ffmpeg color
    subprocess.run(["ffmpeg","-y","-f","lavfi","-i",f"color=c=#0f0f1e:s={WIDTH}x{HEIGHT}:d=0.1","-frames:v","1",BG_GEN])
    return file_ok(BG_GEN)

# Question generation: OpenAI -> GPT4All -> fallback
def generate_questions(topic="Allgemeinwissen", n=NUM_QUESTIONS):
    # Prefer OpenAI API if available (more reliable quality)
    if USE_OPENAI:
        try:
            prompt = f"""
Erzeuge {n} Quizfragen auf Deutsch zum Thema "{topic}".
Gib als reines JSON-Array zurück; jedes Item:
{{"difficulty":"easy|medium|hard|impossible","question":"...","options":[4 strings],"correct":index}}
Reihenfolge: von leicht zu schwer (steigend).
"""
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini", # best-effort; if not available, client will error -> fallback
                messages=[{"role":"user","content":prompt}],
                max_tokens=800,
                temperature=0.8
            )
            txt = resp["choices"][0]["message"]["content"]
            arr = extract_json(txt)
            if arr and isinstance(arr, list) and len(arr)>=n:
                return arr[:n]
        except Exception as e:
            log("OpenAI questions failed:", e)
    # Try GPT4All local
    if GPT4ALL_OK and os.path.isfile("models/ggml-gpt4all-j.bin"):
        try:
            model = GPT4All("models/ggml-gpt4all-j.bin")
            prompt = f"Erzeuge {n} Fragen (Deutsch) in JSON... (kurz)"
            out = model.generate(prompt, max_tokens=600)
            arr = extract_json(out)
            if arr and len(arr)>=n: return arr[:n]
        except Exception as e:
            log("GPT4All failed:", e)
    # Last fallback: templated mixed questions (good quality)
    return fallback_questions(n, topic)

def extract_json(text):
    if not text: return None
    s = text.strip()
    if "[" in s and "]" in s:
        s = s[s.find("["):s.rfind("]")+1]
    try:
        return json.loads(s)
    except Exception:
        return None

def fallback_questions(n, topic):
    # build a small pool and pick n with increasing difficulty
    pool_easy = [
        ("Wie viele Kontinente gibt es?", ["5","6","7","8"], 2),
        ("Welche Farbe hat der Himmel an einem klaren Tag?", ["Grün","Blau","Gelb","Rot"], 1),
        ("Welches Tier produziert Honig?", ["Käfer","Biene","Ameise","Spinne"], 1)
    ]
    pool_med = [
        ("In welchem Jahr war die Mondlandung (erste bemannte)?", ["1957","1969","1979","1989"], 1),
        ("Was ist die Hauptstadt von Kanada?", ["Toronto","Vancouver","Ottawa","Montreal"], 2)
    ]
    pool_hard = [
        ("Welches Element hat das chemische Symbol 'Ag'?", ["Gold","Silber","Argon","Aluminium"], 1)
    ]
    pool_imposs = [
        ("Wie groß ist die Lichtgeschwindigkeit in m/s (ungefähr)?", ["3e6","3e7","3e8","3e9"], 2)
    ]
    seq = ["easy","easy","medium","medium","hard"][:n]
    out=[]
    for dif in seq:
        if dif=="easy":
            q,opts,c = random.choice(pool_easy)
        elif dif=="medium":
            q,opts,c = random.choice(pool_med)
        elif dif=="hard":
            q,opts,c = random.choice(pool_hard)
        else:
            q,opts,c = random.choice(pool_imposs)
        out.append({"difficulty":dif,"question":q,"options":opts,"correct":c})
    return out

# TTS: Piper preferred, else espeak-ng
def find_piper():
    for c in PIPER_CANDS:
        if shutil.which(c) or os.path.isfile(c):
            return c
    return None

def synthesize_tts(text, out_wav):
    text = sanitize(text)
    piper = find_piper()
    if piper:
        # if a model dir exists, try to use it
        model_dir = None
        for d in PIPER_MODEL_DIRS:
            if os.path.isdir(d):
                model_dir = d; break
        try:
            if model_dir:
                cp = subprocess.run([piper,"--model",model_dir,"--text",text,"--out",out_wav], capture_output=True, text=True)
            else:
                cp = subprocess.run([piper,"--text",text,"--out",out_wav], capture_output=True, text=True)
            if cp.returncode==0 and file_ok(out_wav): return out_wav
        except Exception as e:
            log("Piper TTS error:", e)
    # espeak-ng fallback
    try:
        cp = subprocess.run(["espeak-ng","-v","de+f3","-w",out_wav,text], capture_output=True, text=True)
        if cp.returncode==0 and file_ok(out_wav): return out_wav
    except Exception as e:
        log("espeak error:", e)
    return None

# MoviePy advanced build
def build_with_moviepy(questions):
    if not MOVIEPY:
        log("MoviePy not installed.")
        return None
    log("Building animated video via MoviePy...")
    clips=[]
    # base background image clip
    bg = ImageClip(BG_GEN).set_duration(0.1)
    # intro
    intro_txt = TextClip("Teste dein Wissen!", fontsize=76, font="DejaVu-Sans-Bold" if os.path.exists(FONT) else None, color="white", size=(int(WIDTH*0.9),None), method="caption").set_duration(INTRO_DUR)
    intro_bg = ImageClip(BG_GEN).set_duration(INTRO_DUR)
    intro = CompositeVideoClip([intro_bg, intro_txt.set_position(("center","center"))], size=(WIDTH,HEIGHT)).set_fps(FPS)
    clips.append(intro)
    # per question
    for idx,q in enumerate(questions, start=1):
        # quick numeric countdown (3) — compact
        cd = TextClip("3", fontsize=220, color="white", font="DejaVu-Sans-Bold" if os.path.exists(FONT) else None).set_duration(COUNT_DUR)
        cd_clip = CompositeVideoClip([ImageClip(BG_GEN).set_duration(COUNT_DUR), cd.set_position("center")], size=(WIDTH,HEIGHT)).set_fps(FPS)
        clips.append(cd_clip)
        # question with TTS
        qtext = q.get("question","Frage")
        qdur = QUESTION_VIS
        qtxt = TextClip(qtext, fontsize=56, color="white", size=(int(WIDTH*0.9),None), method="caption").set_duration(qdur)
        qbg = ImageClip(BG_GEN).set_duration(qdur)
        q_clip = CompositeVideoClip([qbg, qtxt.set_position(("center", HEIGHT*0.28))], size=(WIDTH,HEIGHT)).set_fps(FPS)
        # tts
        wav = f"q{idx}.wav"
        tts = synthesize_tts(qtext, wav)
        if tts and file_ok(tts):
            try:
                aud = AudioFileClip(tts)
                q_clip = q_clip.set_audio(aud.set_start(0.05))
            except Exception as e:
                log("Load TTS failed:", e)
        clips.append(q_clip)
        # answers block
        opts = q.get("options",[])
        opts_txt = "   ".join([f"{chr(65+i)}: {o}" for i,o in enumerate(opts[:4])])
        ans_dur = ANS_EASY if q.get("difficulty","easy")=="easy" else (ANS_MED if q.get("difficulty")=="medium" else ANS_HARD)
        ans_txt = TextClip(opts_txt, fontsize=44, color="white", size=(int(WIDTH*0.9),None), method="caption").set_duration(ans_dur)
        ans_bg = ImageClip(BG_GEN).set_duration(ans_dur)
        ans_clip = CompositeVideoClip([ans_bg, ans_txt.set_position(("center", HEIGHT*0.55))], size=(WIDTH,HEIGHT)).set_fps(FPS)
        clips.append(ans_clip)
        # reveal
        correct = int(q.get("correct",0))
        corr_text = (opts[correct] if opts and len(opts)>correct else "Lösung")
        rev_txt = TextClip(f"Richtige Antwort: {chr(65+correct)} — {corr_text}", fontsize=60, color="white", size=(int(WIDTH*0.9),None), method="caption").set_duration(REVEAL_DUR)
        rev_bg = ImageClip(BG_GEN).set_duration(REVEAL_DUR)
        rev_clip = CompositeVideoClip([rev_bg, rev_txt.set_position(("center", HEIGHT*0.45))], size=(WIDTH,HEIGHT)).set_fps(FPS)
        clips.append(rev_clip)
    # concat
    final = concatenate_videoclips(clips, method="compose")
    # attach music if present
    if file_ok(MUSIC):
        try:
            music = AudioFileClip(MUSIC).volumex(0.15)
            # collect audio tracks from clips (they already have TTS attached where present)
            audio_tracks=[]
            for c in clips:
                if getattr(c, "audio", None) is not None:
                    audio_tracks.append(c.audio)
            audio_tracks.append(music)
            comp_audio = CompositeAudioClip(audio_tracks)
            final = final.set_audio(comp_audio)
        except Exception as e:
            log("Attach music failed:", e)
    # write out
    out = os.path.join(os.getcwd(), f"quiz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
    try:
        final.write_videofile(out, codec="libx264", audio_codec="aac", fps=FPS, threads=2, preset="medium", ffmpeg_params=["-pix_fmt","yuv420p"])
        return out
    except Exception as e:
        log("MoviePy render failed:", e)
        return None

# Fallback simple FFmpeg pipeline (less animated but robust)
def fallback_pipeline(questions):
    log("Using fallback FFmpeg pipeline...")
    parts=[]
    # intro
    subprocess.run(["ffmpeg","-y","-loop","1","-i",BG_GEN,"-t",str(INTRO_DUR),"-vf",f"scale={WIDTH}:{HEIGHT}","-c:v","libx264","-pix_fmt","yuv420p","intro.mp4"])
    parts.append("intro.mp4")
    for i,q in enumerate(questions, start=1):
        # countdown frame (create one big 3 image)
        subprocess.run(["ffmpeg","-y","-loop","1","-i",BG_GEN,"-t",str(COUNT_DUR),"-vf",f"drawtext=fontfile={FONT}:text='3':fontsize=240:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2","-c:v","libx264","-pix_fmt","yuv420p",f"q{i}_count.mp4"])
        parts.append(f"q{i}_count.mp4")
        qtext = q.get("question","Frage").replace(":", "\\:")
        subprocess.run(["ffmpeg","-y","-loop","1","-i",BG_GEN,"-t",str(QUESTION_VIS),"-vf",f"drawtext=fontfile={FONT}:text='{qtext}':fontsize=56:fontcolor=white:x=(w-text_w)/2:y=h*0.28","-c:v","libx264","-pix_fmt","yuv420p",f"q{i}_q.mp4"])
        parts.append(f"q{i}_q.mp4")
        opts = q.get("options",[])
        opts_txt = "   ".join([f"{chr(65+idx)}: {o}" for idx,o in enumerate(opts[:4])]).replace(":", "\\:")
        dur = ANS_EASY if q.get("difficulty","easy")=="easy" else (ANS_MED if q.get("difficulty")=="medium" else ANS_HARD)
        subprocess.run(["ffmpeg","-y","-loop","1","-i",BG_GEN,"-t",str(dur),"-vf",f"drawtext=fontfile={FONT}:text='{opts_txt}':fontsize=44:fontcolor=white:x=(w-text_w)/2:y=h*0.55","-c:v","libx264","-pix_fmt","yuv420p",f"q{i}_a.mp4"])
        parts.append(f"q{i}_a.mp4")
        corr = int(q.get("correct",0))
        corr_txt = opts[corr] if len(opts)>corr else "Lösung"
        subprocess.run(["ffmpeg","-y","-loop","1","-i",BG_GEN,"-t",str(REVEAL_DUR),"-vf",f"drawtext=fontfile={FONT}:text='Richtige Antwort: {corr_txt}':fontsize=56:fontcolor=white:x=(w-text_w)/2:y=h*0.45","-c:v","libx264","-pix_fmt","yuv420p",f"q{i}_rev.mp4"])
        parts.append(f"q{i}_rev.mp4")
        # tts
        wav = f"q{i}.wav"
        synthesize_tts(q.get("question",""), wav)
    # concat
    with open("concat_list.txt","w",encoding="utf-8") as f:
        for p in parts: f.write(f"file '{p}'\n")
    cp = subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i","concat_list.txt","-c","copy","merged.mp4"], capture_output=True, text=True)
    if cp.returncode != 0:
        log("Concat failed:", cp.stderr)
        return None
    # mix voices and music properly (voices amix then music)
    voice_files = [f"q{i}.wav" for i in range(1, len(questions)+1) if file_ok(f"q{i}.wav")]
    inputs = ["-i","merged.mp4"]
    for v in voice_files: inputs += ["-i", v]
    if file_ok(MUSIC): inputs += ["-i", MUSIC]
    num_voice = len(voice_files)
    has_music = file_ok(MUSIC)
    if num_voice>0 and has_music:
        voice_labels = "".join([f"[{i+1}:a]" for i in range(num_voice)])
        music_idx = num_voice+1
        fc = f"{voice_labels}amix=inputs={num_voice}:duration=longest[vvoices];[{music_idx}:a]volume=0.18[vmusic];[vvoices][vmusic]amix=inputs=2:duration=longest[aout]"
    elif num_voice>0:
        voice_labels = "".join([f"[{i+1}:a]" for i in range(num_voice)])
        fc = f"{voice_labels}amix=inputs={num_voice}:duration=longest[aout]"
    elif has_music:
        fc = "[1:a]volume=0.18[aout]"
    else:
        fc = ""
    cmd = ["ffmpeg","-y"] + inputs
    if fc:
        cmd += ["-filter_complex", fc, "-map","0:v","-map","[aout]","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","final.mp4"]
    else:
        cmd += ["-map","0:v","-c:v","libx264","-pix_fmt","yuv420p","final.mp4"]
    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.returncode != 0:
        log("Final ffmpeg failed:", cp.stderr)
        return None
    final_name = os.path.join(os.getcwd(), f"quiz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
    shutil.move("final.mp4", final_name)
    return final_name

# Main
def main():
    log("Start quiz video generation...")
    if not ensure_background():
        log("Background creation failed.")
        sys.exit(1)
    topic = "Allgemeinwissen"
    questions = generate_questions(topic, NUM_QUESTIONS)
    if not questions or len(questions) < NUM_QUESTIONS:
        log("Question generation failed; abort.")
        sys.exit(1)
    out = None
    if MOVIEPY:
        try:
            out = build_with_moviepy(questions)
        except Exception as e:
            log("MoviePy pipeline error:", e)
            out = None
    if not out:
        out = fallback_pipeline(questions)
    if not out or not file_ok(out):
        log("Failed to produce video.")
        sys.exit(1)
    log("Produced video:", out)
    sys.exit(0)

if __name__ == "__main__":
    main()
