#!/usr/bin/env python3
# compact optimized generate_quiz_video.py (web-editor friendly)
import os, sys, json, random, subprocess
from datetime import datetime

# optional pillow + gpt4all
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    PIL = True
except Exception:
    PIL = False
try:
    from gpt4all import GPT4All
    GPT4ALL = True
except Exception:
    GPT4ALL = False

# ---------- config ----------
WIDTH, HEIGHT = 1080, 1920
BG_UP = "/mnt/data/A_2D_digital_graphic_quiz_image_features_a_dark_bl.png"
BG_GEN = "bg_gen.png"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MODEL = "models/ggml-gpt4all-j.bin"
MUSIC = "music/track1.mp3"
PIPER_CANDS = ["./piper/piper","./piper","piper"]

# short durations tuned for shorts
INTRO=2.0; COUNT=2.5; EASY=2.8; MED=3.2; HARD=3.8; IMP=4.0; REVEAL=1.6

# ---------- helpers ----------
def run(cmd):
    print(">", " ".join(cmd))
    return subprocess.run(cmd, check=False)

def file_ok(p): return os.path.exists(p) and os.path.getsize(p)>0

def sanitize(s): return "".join(c for c in s if 32<=ord(c)<=126)[:120]

# ---------- background ----------
def make_bg():
    if PIL:
        try:
            img = Image.new("RGB",(WIDTH,HEIGHT),(12,12,20))
            d = ImageDraw.Draw(img)
            for y in range(HEIGHT):
                t = y/HEIGHT
                d.line([(0,y),(WIDTH,y)], fill=(int(10+30*t), int(10+10*t), int(18+40*t)))
            if os.path.isfile(BG_UP):
                try:
                    ov = Image.open(BG_UP).convert("RGBA").resize((WIDTH,HEIGHT)).filter(ImageFilter.GaussianBlur(4))
                    ov.putalpha(64)
                    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
                except: pass
            img.save(BG_GEN, quality=85)
            return True
        except Exception as e:
            print("bg error", e)
    # ffmpeg color fallback
    run(["ffmpeg","-y","-f","lavfi","-i","color=c=#0f0f1e:s=1080x1920:d=0.1","-frames:v","1",BG_GEN])
    return True

# ---------- GPT questions (better prompt + parse) ----------
def parse_json_from(s):
    if not s: return None
    s = s.strip()
    if s.find("[")!=-1:
        s = s[s.find("["):s.rfind("]")+1]
    try:
        return json.loads(s)
    except Exception as e:
        print("json parse err", e)
        return None

def gpt_questions(topic="Allgemeinwissen"):
    # try GPT4All
    if GPT4ALL and os.path.isfile(MODEL):
        try:
            m = GPT4All(MODEL)
            prompt = (
                "Erzeuge genau 7 Quizfragen (deutsch) zum Thema '{}'. "
                "Format: JSON-Array mit Objekten {{\"difficulty\":\"easy|medium|hard|impossible\",\"question\":\"...\",\"options\":[4],\"correct\":0-3}}. "
                "Reihenfolge: 3 easy,2 medium,1 hard,1 impossible. Gib nur reines JSON."
            ).format(topic)
            out = m.generate(prompt, max_tokens=600)
            q = parse_json_from(out)
            if q and len(q)==7: return q
        except Exception as e:
            print("gpt4all fail", e)
    # fallback: structured plausible q's
    seq = ["easy","easy","easy","medium","medium","hard","impossible"]
    qlist=[]
    for s in seq:
        if s=="easy":
            q = f"Welches ist ein bekanntes Merkmal von {topic}?"
            opts = [f"{topic} A", f"{topic} B", f"{topic} C", f"{topic} D"]
            corr = random.randint(0,3)
        elif s=="medium":
            q = f"Wodurch zeichnet sich {topic} oft aus?"
            opts = [f"Merkmal {i}" for i in "ABCD"]
            corr = random.randint(0,3)
        elif s=="hard":
            q = f"Welche historische Entwicklung prägte {topic} besonders?"
            opts = ["Entw. A","Entw. B","Entw. C","Entw. D"]; corr=random.randint(0,3)
        else:
            q = f"Sehr spezielle Frage zu {topic} (Trickfrage)."
            opts = ["X","Y","Z","W"]; corr=random.randint(0,3)
        qlist.append({"difficulty":s,"question":q,"options":opts,"correct":corr})
    return qlist

# ---------- TTS: piper preferred, espeak fallback ----------
def find_piper():
    for c in PIPER_CANDS:
        if shutil_which(c): return c
    return None

def shutil_which(x):
    from shutil import which
    return which(x) or os.path.isfile(x)

def synth_voice(text, outwav):
    # try piper (if present)
    p = find_piper()
    if p:
        try:
            run([p,"--text",text,"--out",outwav])
            if file_ok(outwav): return outwav
        except: pass
    # espeak-ng fallback
    run(["espeak-ng","-v","de+f3","-w",outwav,text])
    return outwav if file_ok(outwav) else None

# ---------- small image generator for drawtext usage ----------
def write_txt_image(text,fname,fontsize=64):
    # create a single PNG with centered text on BG_GEN
    try:
        if PIL and os.path.isfile(BG_GEN):
            im = Image.open(BG_GEN).convert("RGB")
            draw = ImageDraw.Draw(im)
            try:
                font = ImageFont.truetype(FONT, fontsize)
            except:
                font = None
            w,h = draw.textsize(text, font=font)
            draw.text(((WIDTH-w)/2,(HEIGHT-h)/2), text, font=font, fill=(255,255,255))
            im.save(fname)
            return True
    except Exception as e:
        print("img write err", e)
    return False

# ---------- ffmpeg clip builders (compact, with animations) ----------
def make_image_clip(imgfile, duration, out):
    run(["ffmpeg","-y","-loop","1","-i",imgfile,"-t",str(duration),"-vf",f"scale={WIDTH}:{HEIGHT},format=yuv420p",out])

def make_text_clip(text,dur,out,fontsize=72):
    tmp="tmp_text.png"
    if not write_txt_image(text,tmp,fontsize): # fallback use bg
        tmp = BG_GEN
    # simple pop-in: fade in scale
    vf = f"format=yuv420p,scale={WIDTH}:{HEIGHT},fade=t=in:st=0:d=0.25,fade=t=out:st={dur-0.25}:d=0.25"
    run(["ffmpeg","-y","-loop","1","-i",tmp,"-t",str(dur),"-vf",vf,out])

def make_countdown(out):
    # create 1-sec frames for 3..1 using drawtext is complex in short file; we emulate with a short static countdown number image + fade
    make_text_clip("3",COUNT, out, fontsize=260)

# ---------- concat and finalize ----------
def concat_files(files, out):
    with open("list.txt","w") as f:
        for p in files: f.write(f"file '{p}'\n")
    run(["ffmpeg","-y","-f","concat","-safe","0","-i","list.txt","-c","copy",out])

def finalize(merged, voices, music, outname):
    # if music present, mix; keep simple: map video + music
    if music and file_ok(music):
        run(["ffmpeg","-y","-i",merged,"-i",music,"-filter_complex","[1:a]volume=0.25[a];[0:a][a]amix=inputs=2:duration=shortest","-c:v","copy","-c:a","aac","-b:a","192k",outname])
    else:
        # re-encode container to ensure compat
        run(["ffmpeg","-y","-i",merged,"-c:v","libx264","-pix_fmt","yuv420p","-movflags","+faststart",outname])

# ---------- main ----------
def main():
    make_bg()
    topic = "Allgemeinwissen"
    qs = gpt_questions(topic)

    parts = []
    voice_files = []

    # intro
    make_text_clip(f"{topic} Quiz", INTRO, "seg_intro.mp4", fontsize=64)
    parts.append("seg_intro.mp4")

    for i,q in enumerate(qs, start=1):
        dif = q.get("difficulty","easy")
        dur = EASY if dif=="easy" else MED if dif=="medium" else HARD if dif=="hard" else IMP
        # countdown
        # we reuse a simple numeric countdown clip (compact)
        make_text_clip("3", COUNT, f"q{i}_count.mp4", fontsize=240)
        parts.append(f"q{i}_count.mp4")
        # announce (question)
        qtext = sanitize(q.get("question","Frage"))
        vw = f"q{i}_q.mp4"
        make_text_clip(qtext, 1.8, vw, fontsize=56)
        parts.append(vw)
        # answers (we display all options concatenated to save time)
        opts = q.get("options", [])
        if opts:
            opts_txt = "   ".join([f"{chr(65+idx)}: {o}" for idx,o in enumerate(opts)])
        else:
            opts_txt = "Antworten: A B C D"
        aout = f"q{i}_a.mp4"
        make_text_clip(opts_txt, dur, aout, fontsize=44)
        parts.append(aout)
        # reveal
        correct = q.get("correct",0)
        corr_txt = (opts[correct] if opts and len(opts)>correct else str(q.get("answer", "Lösung")))
        rev = f"q{i}_rev.mp4"
        make_text_clip("Richtige Antwort: " + corr_txt, REVEAL, rev, fontsize=56)
        parts.append(rev)
        # optional TTS per question (short)
        wav = f"q{i}.wav"
        v = synth_voice(qtext, wav)
        if v: voice_files.append(v)

    # concat
    merged = "merged.mp4"
    concat_files(parts, merged)

    final = f"quiz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    finalize(merged, voice_files, MUSIC if file_ok(MUSIC) else None, final)
    print("final:", final)

if __name__=="__main__":
    main()
