#!/usr/bin/env python3
"""JPEGに「AI生成」の標準メタデータ（IPTC DigitalSourceType = trainedAlgorithmicMedia）を埋め込む。

Instagramは、このIPTC項目を読んで「AI情報」ラベルを自動で付ける仕組みを持つ。
（ChatGPTが入れるC2PAは、PNG→JPEG変換や再保存で消えるため、あらためて入れ直す）

使い方
  python3 add_ai_metadata.py 入力.jpg 出力.jpg
  python3 add_ai_metadata.py in1.jpg in2.jpg in3.jpg --outdir ./out
"""
import argparse
import pathlib
import struct
import sys

XMP = (
    '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about="" '
    'xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" '
    'Iptc4xmpExt:DigitalSourceType='
    '"http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"/>'
    '</rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
).encode("utf-8")
HEADER = b"http://ns.adobe.com/xap/1.0/\x00"


def inject(src: pathlib.Path, dst: pathlib.Path) -> None:
    b = src.read_bytes()
    if b[:2] != b"\xff\xd8":
        sys.exit(f"JPEGではありません: {src}")
    if HEADER in b[:70000] and b"trainedAlgorithmicMedia" in b[:70000]:
        dst.write_bytes(b)  # すでに入っている
        return
    pos = 2
    if b[2:4] == b"\xff\xe0":  # JFIF の直後に入れる
        pos = 2 + 2 + struct.unpack(">H", b[4:6])[0]
    payload = HEADER + XMP
    seg = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    dst.write_bytes(b[:pos] + seg + b[pos:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--outdir")
    a = ap.parse_args()
    if a.outdir is None:
        if len(a.files) != 2:
            sys.exit("出力先: 入力1つ+出力1つ、または --outdir を指定してください")
        inject(pathlib.Path(a.files[0]), pathlib.Path(a.files[1]))
        return
    out = pathlib.Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for f in a.files:
        p = pathlib.Path(f)
        inject(p, out / p.name)
        print("OK:", out / p.name)


if __name__ == "__main__":
    main()
