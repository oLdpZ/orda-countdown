"""Countdown to WoW Forever for the Orda Florentiae Discord.

Renders an animated GIF: the 2004 login-screen gate opening onto the guild's Florence, with the
Dark Portal energy rebuilt from the game's own effect model (hellfire_darkportal_fx.m2: meshes,
textures, additive blending, UV scroll speeds). A webhook keeps one Discord message up to date.

    python countdown.py render out.gif [--at 2026-10-30T12:00:00Z]
    python countdown.py update          # needs WEBHOOK_URL; keeps state in state.json
"""
import argparse, json, math, os, random, struct, sys, wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = Path(__file__).parent
ASSETS = HERE / "assets"
STATE = HERE / "state.json"
LAUNCH_TEXT = HERE / "annuncio-lancio.txt"  # posted with @everyone at launch, only if this file exists

LAUNCH = datetime(2026, 11, 4, 23, 0, tzinfo=timezone.utc)  # midnight 4->5 November, Italian time
TS = int(LAUNCH.timestamp())
CONTENT_COUNTDOWN = f"## 🌀 Il Portale Oscuro si apre su WoW Forever\n**Lancio:** <t:{TS}:F> · <t:{TS}:R>"
CONTENT_OPEN = f"## 🌀 Il portale è aperto!\nWoW Forever è online dal <t:{TS}:F>. Lok'tar Ogar! ⚔️"

W, H = 800, 450
LOOP_MS = 6667  # the slower swirl layer turns one texture repeat in 6667 ms: one seamless loop
N, FRAME_MS = 84, 80
OX0, OY0, OX1, OY1 = 318, 184, 499, 432  # the gate's opening in the login screen
OW, OH = OX1 - OX0, OY1 - OY0
Y0, Y1, Z0, Z1 = -52.61, 56.08, 34.71, 169.19  # the model's portal plane (screen right = +y, up = +z)
GREEN = np.array([0.6863, 0.9137, 0.0])  # the model's colour track for the edge wisps
# edge wisps: (loop ms, fade-out start ms) from the model's global sequences; all fade in over 533 ms
WISP = [(1033, 633), (1233, 833), (1833, 1433), (1400, 1000), (2367, 1967), (1467, 1067), (1933, 1533),
        (1500, 1100), (2167, 1767), (2767, 2367), (1867, 1467), (1633, 533), (2633, 2233)]
FLAMES = [((40, 300, 120, 395), (80, 365)), ((555, 285, 640, 380), (598, 350))]
EYES = [(179, 125), (189, 125), (555, 76), (568, 76), (307, 48), (343, 46)]

PX, PY = np.meshgrid(np.arange(W), np.arange(H))

# launch-night GIF, in three acts over the 84-frame loop: the portal bursts, it stays open, the login queue
ACT_OPEN, ACT_QUEUE = 30, 54
QUEUE = [4832, 4831, 3977, 3120, 2406, 1789, 1203, 777, 404, 250, 133, 69, 42, 17, 8, 3, 2, 1]
JOKES = [
    "Il primo che muore a Durotar paga da bere. 🍺",
    "Zug zug: si lavora fino all'alba, peoni!",
    "Chi chiede \"dove sono i cinghiali?\" va a raccogliere legna per una settimana.",
    "Ricordate: il lupo è una cavalcatura, non un cane da accarezzare in mezzo alla strada.",
    "Vietato fare \"Leeroy\" nella prima istanza. Nella seconda si vede.",
    "Stanotte niente Firenze: la capitale è Orgrimmar. Il lampredotto lo portate voi.",
    "Se lagga è colpa dell'Alleanza. Sempre.",
    "Chi resta in coda più di un'ora ha diritto a lamentarsi in chat. Ma solo in orchesco.",
    "Il raduno è nella Valle delle Prove: chi arriva ultimo porta i cinghiali per tutti.",
    "Lok'tar Ogar! (traduzione per i nuovi: \"stanotte non si dorme\").",
]


def blob(x, y, sx, sy):
    return np.exp(-(((PX - x) / sx) ** 2 + ((PY - y) / sy) ** 2))


def soft(mask, r):
    return np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(r))) / 255.0


def texture(fid, size=None):
    im = Image.open(ASSETS / "m2" / f"{fid}.bin").convert("RGBA")
    if size:
        im = im.resize(size, Image.LANCZOS)
    return np.asarray(im).astype(float) / 255.0


def sample(tex, u, v):
    th, tw = tex.shape[:2]
    return tex[(np.clip(v, 0, 1) * (th - 1)).astype(int), (np.mod(u, 1) * (tw - 1)).astype(int)]


class Portal:
    """The model's meshes rasterised front-on into the gate's opening: per-pixel u, v and coverage."""

    def __init__(self):
        raw = (ASSETS / "m2" / "192920.bin").read_bytes()
        md = raw[8:8 + struct.unpack_from("<I", raw, 4)[0]]
        vn, vo = struct.unpack_from("<II", md, 60)
        self.verts = [struct.unpack_from("<3f4B4B3f2f2f", md, vo + 48 * i) for i in range(vn)]
        sk = (ASSETS / "m2" / "496255.bin").read_bytes()
        n, o = struct.unpack_from("<II", sk, 4)
        self.vidx = struct.unpack_from(f"<{n}H", sk, o)
        n, o = struct.unpack_from("<II", sk, 12)
        self.tris = struct.unpack_from(f"<{n}H", sk, o)
        n, o = struct.unpack_from("<II", sk, 28)
        self.subs = [struct.unpack_from("<6H", sk, o + 48 * i) for i in range(n)]
        swirl = texture(192922, (512, 256))
        # submesh: (texture, UV scroll period in ms, weight), in draw order; all additive
        self.layers = {14: (texture(192921, (256, 256)), None, 1.0), 17: (texture(197067, (512, 512)), None, 0.5),
                       13: (swirl, 3333, 1.0), 18: (swirl, 6667, 1.0)}
        self.wisp = texture(144322)
        self.uv = {s: self.raster(s) for s in list(self.layers) + list(range(13))}

    def raster(self, sub):
        U, V, C = np.zeros((H, W)), np.zeros((H, W)), np.zeros((H, W))
        istart, icount = self.subs[sub][4:6]
        for t in range(istart, istart + icount, 3):
            P = []
            for j in self.tris[t:t + 3]:
                v = self.verts[self.vidx[j]]
                P.append((OX0 + (v[1] - Y0) / (Y1 - Y0) * OW, OY0 + (Z1 - v[2]) / (Z1 - Z0) * OH, v[14], v[15]))
            (x0, y0, u0, w0), (x1, y1, u1, w1), (x2, y2, u2, w2) = P
            den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(den) < 1e-9:
                continue
            bx0, bx1 = int(max(0, min(x0, x1, x2))), int(min(W - 1, max(x0, x1, x2)) + 1)
            by0, by1 = int(max(0, min(y0, y1, y2))), int(min(H - 1, max(y0, y1, y2)) + 1)
            X, Y = PX[by0:by1, bx0:bx1] + 0.5, PY[by0:by1, bx0:bx1] + 0.5
            a = ((y1 - y2) * (X - x2) + (x2 - x1) * (Y - y2)) / den
            b = ((y2 - y0) * (X - x2) + (x0 - x2) * (Y - y2)) / den
            c = 1 - a - b
            inside = (a >= -0.01) & (b >= -0.01) & (c >= -0.01)
            win = (slice(by0, by1), slice(bx0, bx1))
            U[win] = np.where(inside, a * u0 + b * u1 + c * u2, U[win])
            V[win] = np.where(inside, a * w0 + b * w1 + c * w2, V[win])
            C[win] = np.maximum(C[win], inside)
        return U, V, soft(C, 0.8)

    def draw(self, dest, ms):
        """Additive energy layers over `dest` (0..1), at time `ms` in the loop."""
        p = dest.copy()
        for sub, (tex, period, weight) in self.layers.items():
            U, V, C = self.uv[sub]
            if period:  # texture transform: u slides by -1 every `period` ms, a counter-clockwise turn
                U = U + ms / period
            t = sample(tex, U, V)
            p += t[..., :3] * t[..., 3:] * C[..., None] * weight
        for i, (loop, fade) in enumerate(WISP):
            fit = LOOP_MS / round(LOOP_MS / loop)  # stretch each loop slightly so the GIF repeats seamlessly
            t = (ms + 300 * i) % fit
            a = t / 533 if t < 533 else 1.0 if t < fade else max(0.0, 1 - (t - fade) / max(1, fit - fade))
            if a > 0:
                U, V, C = self.uv[i]
                s = sample(self.wisp, U, V)
                p += s[..., :3] * s[..., 3:] * GREEN * a * C[..., None]
        return np.clip(p, 0, 1)


class Lettering:
    """Static metal lettering in the Forever logo's style: colour, alpha and the letter mask for the shine."""

    def __init__(self):
        self.rgb, self.a, self.letters = np.zeros((H, W, 3)), np.zeros((H, W)), np.zeros((H, W))

    def _over(self, col, al):
        self.rgb = self.rgb * (1 - al[..., None]) + col * al[..., None]
        self.a = self.a + al * (1 - self.a)

    def text(self, xy, text, size, glow=True):
        m = Image.new("L", (W, H))
        ImageDraw.Draw(m).text(xy, text, font=ImageFont.truetype(str(ASSETS / "MORPHEUS.TTF"), size), fill=255, anchor="mm")
        a = np.asarray(m) / 255.0
        if glow:  # warm outer glow, like the braziers' light
            self._over(np.array([255, 120, 20]), 0.6 * np.asarray(m.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(9))) / 255.0)
        self._over(np.array([35, 14, 4]), np.asarray(m.filter(ImageFilter.MaxFilter(5))) / 255.0)
        b = m.getbbox()
        t = np.clip((PY - b[1]) / max(1, b[3] - b[1]), 0, 1)
        fill = np.stack([255 - 60 * t ** 1.5, 246 - 120 * t, 215 - 175 * t], -1)  # cream to bronze
        gy, gx = np.gradient(np.asarray(m.filter(ImageFilter.GaussianBlur(2))) / 255.0)
        fill = np.clip(fill + np.clip(-(gx + gy) * 6, -1, 1)[..., None] * 70, 0, 255)  # bevel, light from top-left
        self._over(fill, a)
        self.letters = np.maximum(self.letters, a)


def render(now, out):
    left = LAUNCH - now
    is_open = left.total_seconds() <= 0
    base = np.asarray(Image.open(ASSETS / "login.jpg").convert("RGB").resize((W, H), Image.LANCZOS)).astype(float)
    opening = soft(((PX >= OX0) & (PX < OX1) & (PY >= OY0) & (PY < OY1)).astype(float), 1.5)

    # Florence: the portal's destination, in place of the model's star field; dimmed to match it until opening night
    art = Image.open(ASSETS / "firenze.png").convert("RGB")
    s = OH / art.height
    art = art.resize((round(art.width * s), OH), Image.LANCZOS)
    ax = round(300 * s) - OW // 2 - 4  # centre the lion
    florence = np.zeros((H, W, 3))
    florence[OY0:OY1, OX0:OX1] = np.asarray(art.crop((ax, 0, ax + OW, OH))) / 255.0 * (0.9 if is_open else 0.62)

    cx = (OX0 + OX1) // 2
    lt = Lettering()
    if is_open:
        lt.text((cx, 380), "World of Warcraft Forever", 15, glow=False)
        lt.text((cx, 414), "Il portale è aperto", 32)
        # the war cry, at three sizes for the pulse of the opening act
        shouts = []
        for size in (50, 56, 62):
            sh = Lettering()
            sh.text((W // 2, 405), "LOK'TAR OGAR!", size)
            shouts.append(sh)
        small = ImageFont.load_default(size=15)
        title = ImageFont.truetype(str(ASSETS / "MORPHEUS.TTF"), 22)
    else:
        lt.text((cx, 372), "Il portale si apre tra", 16, glow=False)
        if left.days:
            big, units = (left.days, left.seconds // 3600), ("giorni", "ore")
        else:  # last day: hours and minutes, refreshed every minute by cron-job.org
            big, units = (left.seconds // 3600, left.seconds // 60 % 60), ("ore", "minuti")
        lt.text((cx, 404), f"{big[0]:02d} : {big[1]:02d}", 54)
        lt.text((cx - 39, 440), units[0], 14, glow=False)
        lt.text((cx + 39, 440), units[1], 14, glow=False)
    band = soft(((PX >= OX0 - 30) & (PX < OX1 + 30) & (PY >= 358)).astype(float), 12)

    logo = Image.open(ASSETS / "forever_logo.png").convert("RGBA")
    logo.thumbnail((118, 96), Image.LANCZOS)
    logo_xy = (W - logo.width - 10, H - logo.height - 6)

    lum = base.mean(-1)
    flame_mask = np.zeros((H, W))
    for (x0, y0, x1, y1), _ in FLAMES:
        flame_mask[(PX >= x0) & (PX < x1) & (PY >= y0) & (PY < y1) & (lum > 150) & (base[..., 0] > 200)] = 1
    flame_mask = soft(flame_mask, 2)
    rnd = random.Random(7)
    embers = [(rnd.choice(FLAMES)[1], rnd.uniform(-25, 25), rnd.uniform(0, 1), rnd.choice([2, 3]), rnd.uniform(0, 6.28)) for _ in range(26)]
    portal = Portal()

    frames = []
    for k in range(N):
        ms, ph = LOOP_MS * k / N, 2 * math.pi * k / N
        # braziers: wobble the flame pixels and pulse their light on the stone
        flick = [0.8 + 0.12 * math.sin(ph * 9 + i) + 0.08 * math.sin(ph * 14 + 2 * i) for i in range(2)]
        wob = base[PY, np.clip(PX + np.round(2.5 * np.sin(PY * 0.25 - ph * 12)).astype(int), 0, W - 1)]
        fl = np.where(PX < W / 2, flick[0], flick[1])[..., None]
        f = base * (1 - flame_mask[..., None]) + np.clip(wob * (0.75 + 0.35 * fl), 0, 255) * flame_mask[..., None]
        for i, (_, (gx, gy)) in enumerate(FLAMES):
            f += blob(gx, gy - 30, 110, 120)[..., None] * np.array([90, 40, 5]) * (flick[i] - 0.65)
        eye = 0.6 + 0.4 * math.sin(ph * 3)
        for ex, ey in EYES:
            f += blob(ex, ey, 6, 5)[..., None] * np.array([220, 30, 20]) * eye
        f = f * (1 - opening[..., None]) + portal.draw(florence, ms) * 255 * opening[..., None]
        f = f * (1 - 0.65 * band[..., None])
        img = Image.fromarray(np.clip(f, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        for (gx, gy), dx, y0, cyc, sway in embers:
            t = (y0 + cyc * k / N) % 1
            x, y, a = gx + dx + 8 * math.sin(sway + t * 9), gy - 40 - t * 260, 1 - t
            r = 1.6 * a + 0.6
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, int(120 + 100 * a), int(30 * a)))
        f = np.asarray(img).astype(float)
        cur = lt
        if is_open and k < ACT_OPEN:  # act 1: the portal bursts green, then the war cry pulses
            cur = shouts[[0, 1, 2, 1][k % 4]]
            t = k / ACT_OPEN
            burst = math.exp(-((t - 0.12) / 0.09) ** 2)  # white flash peaks early in the act
            ring = np.exp(-((np.hypot(PX - cx, (PY - (OY0 + OY1) / 2) * 1.3) - 900 * t) / 60) ** 2) * (1 - t)
            glow = blob(cx, (OY0 + OY1) / 2, 160 + 500 * t, 200 + 500 * t) * (1 - t) * 0.9
            g = np.clip(ring + glow, 0, 1)[..., None] * np.array([140, 255, 40])
            f = np.clip(f + g, 0, 255) * (1 - burst) + np.array([235, 255, 210]) * burst
        shine = np.exp(-(((PX + PY * 0.5) - (-150 + (W + 450) * ((3 * k / N) % 1))) / 14.0) ** 2) * cur.letters
        queue = is_open and k >= ACT_QUEUE
        if not queue:  # act 3 has no lettering: the queue box takes the band
            f = f * (1 - cur.a[..., None]) + cur.rgb * cur.a[..., None] + shine[..., None] * 110
        img = Image.fromarray(np.clip(f, 0, 255).astype(np.uint8))
        if queue:
            queue_box(img, QUEUE[min(len(QUEUE) - 1, (k - ACT_QUEUE) * len(QUEUE) // (N - ACT_QUEUE - 6))], title, small)
        img.paste(logo, logo_xy, logo)
        frames.append(img)

    # one palette for the whole loop, taken from four frames spread over it plus extra logo
    # samples, so its small blue area keeps colours of its own
    picks = [2, 8, 20, ACT_OPEN + 5, ACT_QUEUE + 5, N - 1] if is_open else [i * N // 4 for i in range(4)]
    strip = Image.new("RGB", (W, H * (len(picks) + 1)))
    for i, fi in enumerate(picks):
        strip.paste(frames[fi], (0, H * i))
    tile = frames[0].crop((logo_xy[0], logo_xy[1], logo_xy[0] + logo.width, logo_xy[1] + logo.height))
    for x in range(0, W, tile.width):
        for y in range(H * len(picks), H * (len(picks) + 1), tile.height):
            strip.paste(tile, (x, y))
    pal = strip.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    q[0].save(out, save_all=True, append_images=q[1:], duration=FRAME_MS, loop=0, optimize=True)
    return is_open


def queue_box(img, pos, title, small):
    """A 2004-style realm queue dialog: dark panel, gold frame, position counting down."""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = W // 2 - 175, 352, W // 2 + 175, 446
    d.rectangle((x0, y0, x1, y1), fill=(12, 8, 6), outline=(200, 160, 60), width=3)
    d.rectangle((x0 + 5, y0 + 5, x1 - 5, y1 - 5), outline=(90, 60, 20), width=1)
    cx = W // 2
    if pos > 1:
        d.text((cx, y0 + 22), "Il reame Orda Florentiae è pieno", font=title, fill=(255, 210, 0), anchor="mm")
        d.text((cx, y0 + 50), f"Posizione in coda: {pos:,}".replace(",", "."), font=small, fill=(255, 255, 255), anchor="mm")
        d.text((cx, y0 + 72), "Tempo stimato: Lok'tar", font=small, fill=(200, 200, 200), anchor="mm")
    else:
        d.text((cx, y0 + 28), "Posizione in coda: 1", font=title, fill=(255, 210, 0), anchor="mm")
        d.text((cx, y0 + 62), "Benvenuto a casa, peone. Zug zug!", font=small, fill=(140, 255, 60), anchor="mm")


def horn(path):
    """An original war-horn call, synthesised: two long low blasts and a rising third, 16-bit mono WAV."""
    sr = 22050
    out = []
    for dur, f0, f1 in [(1.1, 98, 98), (1.1, 98, 98), (2.2, 98, 147)]:
        t = np.arange(int(sr * dur)) / sr
        f = f0 + (f1 - f0) * np.clip(t / (dur * 0.6), 0, 1) ** 2 + 1.5 * np.sin(2 * np.pi * 5 * t) * (t / dur)
        ph = 2 * np.pi * np.cumsum(f) / sr
        x = sum(a * np.sin(n * ph) for n, a in [(1, 1), (2, 0.7), (3, 0.5), (4, 0.3), (5, 0.18), (6, 0.1)])
        x = np.tanh(1.6 * x)  # brassy grit
        env = np.minimum(1, t / 0.12) * np.minimum(1, (dur - t) / 0.35)
        out += [x * env, np.zeros(int(sr * 0.18))]
    y = np.concatenate(out)
    y = (y / np.abs(y).max() * 0.85 * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(y.tobytes())


def send(method, url, content, gif=None, ping=False, audio=None):
    import requests
    payload = {"content": content, "allowed_mentions": {"parse": ["everyone"] if ping else []}}
    files = {}
    if gif:
        payload["attachments"] = [{"id": 0, "filename": "portale.gif"}]  # replaces the previous GIF
        files["files[0]"] = ("portale.gif", open(gif, "rb"), "image/gif")
    if audio:
        payload["attachments"] = [{"id": 0, "filename": "corno-di-guerra.wav"}]
        files["files[0]"] = ("corno-di-guerra.wav", open(audio, "rb"), "audio/wav")
    r = requests.request(method, url, data={"payload_json": json.dumps(payload)}, files=files or None, timeout=120)
    if r.status_code >= 300:
        sys.exit(f"Discord {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}


def update():
    hook = os.environ["WEBHOOK_URL"].rstrip("/")
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    now = datetime.now(timezone.utc)
    if state.get("launched"):
        print("already launched, nothing to do")
        return
    gif = HERE / "portale.gif"
    is_open = render(now, gif)
    content = CONTENT_OPEN if is_open else CONTENT_COUNTDOWN
    if state.get("message_id"):
        send("PATCH", f"{hook}/messages/{state['message_id']}", content, gif)
    else:
        state["message_id"] = send("POST", f"{hook}?wait=true", content, gif)["id"]
    if is_open:
        if LAUNCH_TEXT.exists():
            text = LAUNCH_TEXT.read_text(encoding="utf-8").strip() + "\n\n🎲 " + random.choice(JOKES)
            text += "\n🎵 Per tornare al 2004, la musica del login originale: *Legends of Azeroth* → https://warcraft.wiki.gg/wiki/Legends_of_Azeroth"
            text += "\n🔊 Premete play: il corno di guerra chiama l'Orda!"
            try:
                horn(HERE / "corno.wav")
                send("POST", hook, text, ping=True, audio=HERE / "corno.wav")
            except BaseException as e:  # never lose the announcement over the horn
                print("horn failed:", e)
                send("POST", hook, text.rsplit("\n", 1)[0], ping=True)
        state["launched"] = True
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    print("updated", state, gif.stat().st_size)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("out")
    r.add_argument("--at", help="render as if it were this UTC time, e.g. 2026-11-05T00:00:00Z")
    sub.add_parser("update")
    sub.add_parser("horn").add_argument("out")
    args = ap.parse_args()
    if args.cmd == "render":
        at = datetime.fromisoformat(args.at.replace("Z", "+00:00")) if args.at else datetime.now(timezone.utc)
        print("open" if render(at, args.out) else "countdown", Path(args.out).stat().st_size)
    elif args.cmd == "horn":
        horn(args.out)
        print(random.choice(JOKES))
    else:
        update()
