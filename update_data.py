#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
決算図書館 データ更新スクリプト
================================
使い方:
    python3 update_data.py

やること:
    1. data/ フォルダ内の CSV を読み込む
    2. blog/ フォルダの HTML を確認して記事あり/なし判定
    3. blog-index.html の BLOG_JP_DATA を自動書き換え

CSV フォーマット（1行目がヘッダー）:
    証券コード, 企業名, 株価, 時価総額(億円), PER, PBR, ROE(%), 配当利回り(%)
"""

import csv
import os
import re
import json
import glob
from pathlib import Path

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent                  # このスクリプトと同じフォルダ
DATA_DIR   = BASE_DIR / "data"                      # CSVを置くフォルダ
BLOG_DIR   = BASE_DIR / "blog"                      # 記事HTMLフォルダ
INDEX_HTML = BASE_DIR / "blog-index.html"           # 更新対象

# タグ自動判定の閾値（必要に応じて調整）
THRESHOLDS = {
    "高配当株": lambda dy, per, pbr, roe, mc: dy  is not None and dy  >= 3.5,
    "割安株":   lambda dy, per, pbr, roe, mc: pbr is not None and pbr <= 1.0,
    "成長株":   lambda dy, per, pbr, roe, mc: roe is not None and roe >= 15,
    "大型株":   lambda dy, per, pbr, roe, mc: mc  is not None and mc  >= 5000,
    "小型株":   lambda dy, per, pbr, roe, mc: mc  is not None and mc  < 500,
}

# ─────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────
def parse_float(v):
    try:
        v = str(v).strip()
        return round(float(v), 2) if v else None
    except:
        return None


def get_col(row, *names):
    """列名の揺れを吸収：複数の候補名を順に試す"""
    for name in names:
        if name in row and str(row[name]).strip():
            return row[name]
    return ""


def auto_tags(dy, per, pbr, roe, mc):
    return [tag for tag, fn in THRESHOLDS.items() if fn(dy, per, pbr, roe, mc)]


def get_html_files(blog_dir):
    """code -> filename の辞書を返す"""
    result = {}
    for f in Path(blog_dir).glob("*.html"):
        code = f.name.split("_")[0]
        result[code] = f.name
    return result


def load_existing_entries(html_path):
    """
    blog-index.html 内の BLOG_JP_DATA から既存エントリを読み込む
    → 手動設定した tags / videoUrl / prevUrl / fy / period を保持するため
    """
    existing = {}
    with open(html_path, encoding="utf-8") as f:
        content = f.read()

    # JSONっぽくないのでregexで抽出（簡易パース）
    m = re.search(r"const BLOG_JP_DATA = \[(.*?)\];", content, re.DOTALL)
    if not m:
        return existing

    block = m.group(1)
    for entry in re.finditer(
        r'\{\s*date:("[^"]*")'
        r'.*?code:("[^"]*")'
        r'.*?name:("[^"]*")'
        r'.*?tags:(\[[^\]]*\])'
        r'.*?url:(null|"[^"]*")'
        r'.*?videoUrl:(null|"[^"]*")'
        r'.*?prevUrl:(null|"[^"]*")'
        r'.*?fy:(null|"[^"]*")'
        r'.*?period:(null|"[^"]*")',
        block,
        re.DOTALL
    ):
        g = entry.groups()
        code_raw = g[1].strip('"')
        existing[code_raw] = {
            "date":     g[0].strip('"'),
            "name":     g[2].strip('"'),
            "tags":     json.loads(g[3].replace("'", '"')),
            "url":      None if g[4] == "null" else g[4].strip('"'),
            "videoUrl": None if g[5] == "null" else g[5].strip('"'),
            "prevUrl":  None if g[6] == "null" else g[6].strip('"'),
            "fy":       None if g[7] == "null" else g[7].strip('"'),
            "period":   None if g[8] == "null" else g[8].strip('"'),
        }
    return existing


def find_csv(data_dir):
    """data/ 内の CSV を探す（複数あれば更新日時が最新のもの）"""
    files = list(Path(data_dir).glob("*.csv"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────
def build_entries(csv_path, html_files, existing):
    entries = []
    csv_codes = set()

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row["証券コード"].strip()
            name = row["企業名"].strip()
            mc   = parse_float(get_col(row, "時価総額(億円)", "時価総額"))
            per  = parse_float(get_col(row, "PER", "PER(倍)"))
            pbr  = parse_float(get_col(row, "PBR", "PBR(倍)"))
            roe  = parse_float(get_col(row, "ROE(%)", "ROE"))
            dy   = parse_float(get_col(row, "配当利回り(%)", "配当利回り", "配当利回り(%)"))

            csv_codes.add(code)

            ex   = existing.get(code, {})
            tags = ex.get("tags") or auto_tags(dy, per, pbr, roe, mc)
            url  = ex.get("url") or (f"blog/{html_files[code]}" if code in html_files else None)

            entries.append({
                "date":          ex.get("date", "2026-04-13"),
                "code":          code,
                "name":          name,
                "tags":          tags,
                "url":           url,
                "videoUrl":      ex.get("videoUrl"),
                "prevUrl":       ex.get("prevUrl"),
                "fy":            ex.get("fy"),
                "period":        ex.get("period"),
                "dividendYield": dy,
                "per":           per,
                "pbr":           pbr,
                "roe":           roe,
                "marketCap":     mc,
                "equityRatio":   None,
                "payoutRatio":   None,
                "dividendGrowth":None,
            })

    # CSV にないが HTML 記事がある会社を末尾に追加
    for code, fname in sorted(html_files.items()):
        if code in csv_codes:
            continue
        ex   = existing.get(code, {})
        name = ex.get("name") or fname.split("_")[1] if "_" in fname else code
        tags = ex.get("tags") or ["高配当株"]
        entries.append({
            "date":          ex.get("date", "2026-04-13"),
            "code":          code,
            "name":          name,
            "tags":          tags,
            "url":           ex.get("url", f"blog/{fname}"),
            "videoUrl":      ex.get("videoUrl"),
            "prevUrl":       ex.get("prevUrl"),
            "fy":            ex.get("fy"),
            "period":        ex.get("period"),
            "dividendYield": None,
            "per":           None,
            "pbr":           None,
            "roe":           None,
            "marketCap":     None,
            "equityRatio":   None,
            "payoutRatio":   None,
            "dividendGrowth":None,
        })

    # コード順ソート（数字 → 英数字）
    def sort_key(e):
        c = e["code"]
        return (0, int(c)) if c.isdigit() else (1, c)
    entries.sort(key=sort_key)
    return entries


def entries_to_js(entries):
    def j(v):
        return "null" if v is None else json.dumps(v, ensure_ascii=False)

    lines = []
    for e in entries:
        tags_js = "[" + ",".join(json.dumps(t, ensure_ascii=False) for t in e["tags"]) + "]"
        lines.append(
            f'  {{ date:{j(e["date"])}, code:{j(e["code"])}, name:{j(e["name"])}, '
            f'tags:{tags_js}, url:{j(e["url"])}, videoUrl:{j(e["videoUrl"])}, prevUrl:{j(e["prevUrl"])}, '
            f'fy:{j(e["fy"])}, period:{j(e["period"])}, '
            f'dividendYield:{j(e["dividendYield"])}, per:{j(e["per"])}, pbr:{j(e["pbr"])}, '
            f'roe:{j(e["roe"])}, marketCap:{j(e["marketCap"])}, '
            f'equityRatio:{j(e["equityRatio"])}, payoutRatio:{j(e["payoutRatio"])}, '
            f'dividendGrowth:{j(e["dividendGrowth"])} }}'
        )
    return "const BLOG_JP_DATA = [\n" + ",\n".join(lines) + "\n];"


def update_html(html_path, new_js):
    with open(html_path, encoding="utf-8") as f:
        content = f.read()

    pattern = r"// ★ BLOG_JP_DATA.*?const BLOG_JP_DATA = \[.*?\];"
    replacement = "// ★ BLOG_JP_DATA — Python自動書き込みエリア（日本株）\n" + new_js
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    if new_content == content:
        print("⚠️  blog-index.html 内の BLOG_JP_DATA が見つかりません（スキップ）")
        return False

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True


def main():
    print("=" * 50)
    print("  決算図書館 データ更新スクリプト")
    print("=" * 50)

    # data/ フォルダ確認
    DATA_DIR.mkdir(exist_ok=True)
    csv_path = find_csv(DATA_DIR)
    if csv_path is None:
        print(f"\n❌  CSV が見つかりません。")
        print(f"    {DATA_DIR}/ に CSV を置いてください。")
        print(f"\n    期待するフォーマット（1行目ヘッダー）:")
        print(f"    証券コード,企業名,株価,時価総額(億円),PER,PBR,ROE(%),配当利回り(%)")
        return

    print(f"\n📂  CSV: {csv_path.name}")
    print(f"📂  ブログ記事: {BLOG_DIR}")
    print(f"📄  更新対象: {INDEX_HTML.name}")

    # データ収集
    html_files = get_html_files(BLOG_DIR)
    existing   = load_existing_entries(INDEX_HTML)
    entries    = build_entries(csv_path, html_files, existing)

    with_article = sum(1 for e in entries if e["url"])
    with_video   = sum(1 for e in entries if e["videoUrl"])

    print(f"\n📊  集計:")
    print(f"    全銘柄数   : {len(entries):,} 社")
    print(f"    記事あり   : {with_article:,} 社")
    print(f"    記事なし   : {len(entries) - with_article:,} 社（準備中）")
    print(f"    動画あり   : {with_video:,} 社")

    # HTML 更新
    new_js = entries_to_js(entries)
    ok = update_html(INDEX_HTML, new_js)

    if ok:
        size_kb = INDEX_HTML.stat().st_size // 1024
        print(f"\n✅  blog-index.html を更新しました（{size_kb} KB）")
        print(f"\n次のステップ:")
        print(f"    git add blog-index.html")
        print(f"    git commit -m '銘柄データ更新'")
        print(f"    git push origin main")
    print()


if __name__ == "__main__":
    main()
