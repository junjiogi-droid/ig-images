"""ファイル名 -> Instagramカルーセル(正面/横顔/情報カード) + キャプションを生成"""
import re, sys, json, pathlib
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350  # Instagram 4:5
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_R = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
INK, ACCENT, BG = (60, 42, 36), (125, 90, 80), (246, 242, 237)

def parse(name):
    d, style, color, outfit, bg, angle = pathlib.Path(name).stem.split("_")
    return dict(date=d, style=style, color=color, outfit=outfit, bg=bg, angle=angle)

def fit(path):
    im = Image.open(path).convert("RGB")
    return im.resize((W, int(im.height * W / im.width)), Image.LANCZOS).crop((0, 0, W, H))

def wrap(draw, text, font, width):
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > width:
            lines.append(cur); cur = ch
        else:
            cur += ch
    return lines + [cur]

def info_card(meta, tips, out):
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    f = lambda s, b=True: ImageFont.truetype(FONT if b else FONT_R, s, index=0)
    d.text((80, 90), "SAVE", font=f(30), fill=ACCENT)
    d.text((80, 140), "美容室で見せるだけ", font=f(64), fill=INK)
    d.text((80, 225), "オーダーメモ", font=f(64), fill=INK)
    d.line((80, 330, W - 80, 330), fill=ACCENT, width=3)
    y = 380
    for label, val in (("STYLE", meta["style"]), ("COLOR", meta["color"])):
        d.text((80, y), label, font=f(28), fill=ACCENT)
        for ln in wrap(d, val, f(46), W - 160):
            y += 42; d.text((80, y), ln, font=f(46), fill=INK); y += 22
        y += 90
    d.text((80, y), "ORDER TIPS", font=f(28), fill=ACCENT); y += 70
    for t in tips:
        for i, ln in enumerate(wrap(d, t, f(36, False), W - 200)):
            if i == 0: d.text((80, y + 10), "●", font=f(24), fill=ACCENT)
            d.text((130, y), ln, font=f(36, False), fill=INK); y += 52
        y += 14
    d.text((80, H - 90), "※AI生成イメージです。仕上がりは髪質・骨格で変わります", font=f(24, False), fill=ACCENT)
    im.save(out, quality=95)

def caption(meta, tags):
    return (f"【{meta['style']}】{meta['color']}\n\n"
            f"正面と横顔でシルエットをチェック。3枚目は保存して、美容室でそのまま見せられるオーダーメモです。\n\n"
            f"※AI生成イメージです。実際の仕上がりは髪質・骨格・ダメージ状態で変わります。\n\n"
            + " ".join(tags))

if __name__ == "__main__":
    front, side, outdir = sys.argv[1], sys.argv[2], pathlib.Path(sys.argv[3])
    outdir.mkdir(parents=True, exist_ok=True)
    meta = parse(front)
    tips = json.loads(sys.argv[4])
    tags = ["#クラビカット", "#ミディアムレイヤー", "#くすみカラー", "#大人ヘア", "#髪型オーダー", "#AI生成"]
    fit(front).save(outdir / "1_front.jpg", quality=95)
    fit(side).save(outdir / "2_side.jpg", quality=95)
    info_card(meta, tips, outdir / "3_info.jpg")
    (outdir / "caption.txt").write_text(caption(meta, tags), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))
