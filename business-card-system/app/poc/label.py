"""実名刺に正解ラベルを付けるための入力画面。

    PYTHONPATH=src .venv/bin/python poc/label.py ./poc/real-cards

ブラウザで http://127.0.0.1:8100/ を開き、名刺画像を見ながら項目を入力する。
画像と同じ名前の `.json` が同じフォルダに保存され、そのまま
`poc/runner.py --real` で精度測定に使える。

OCR精度の比較（論点C）には、**人が確認した正解**が要る。
この画面はその作成を楽にするためのもので、外部へは何も送信しない。

## 目安

名刺1枚あたり14項目、40枚で560項目になる。1枚1〜2分として1時間強。
記載のない項目は空欄のままでよい（空欄も「その項目は無い」という正解になる）。

## OCRの下書きについて

既定でOCRが下書きを入れる（実際のアプリと同じ流れ）。OCRが入れた欄は
**黄色＋「未確認」**で示され、その欄に触れると印が消える。

保存時、触っていない欄は `_unverified` として記録する。
その正解ラベルで精度を測ると `poc/runner.py` が警告を出す。
OCRの下書きをそのまま正解にすると、測定値が実際より良く出るため。

空欄から入力したい場合は `--no-prefill` を付ける。
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `python poc/label.py` でも動くように

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse  # noqa: E402

from poc.samples import FIELD_KEYS  # noqa: E402

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".heic", ".pdf")

LABELS = {
    "last_name": "姓",
    "first_name": "名",
    "last_name_kana": "姓（ふりがな）",
    "first_name_kana": "名（ふりがな）",
    "company_name": "会社名",
    "department_name": "部署",
    "title": "役職",
    "postal_code": "郵便番号",
    "address": "住所",
    "tel": "電話",
    "mobile": "携帯",
    "fax": "FAX",
    "email": "メール",
    "url": "URL",
}

HINTS = {
    "last_name": "例: 山田",
    "first_name": "例: 太郎",
    "last_name_kana": "名刺に記載が無ければ空欄",
    "first_name_kana": "名刺に記載が無ければ空欄",
    "company_name": "「株式会社」も含めて記載どおりに",
    "department_name": "例: 営業本部 第一営業部",
    "title": "例: 部長",
    "postal_code": "例: 100-0001（〒は不要）",
    "address": "記載どおりに。改行は空白1つに",
    "tel": "記載どおりに（ハイフンも）",
    "mobile": "携帯番号。無ければ空欄",
    "fax": "無ければ空欄",
    "email": "",
    "url": "例: https://www.example.co.jp",
}


def _version() -> str:
    """この画面がどの版かを返す。

    「最新版に更新する」を実行したつもりで取得できていない、という取り違えが
    実際に起きた。画面に版を出して、その場で確かめられるようにする。
    """
    import subprocess

    root = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%h %cd", "--date=format:%m/%d %H:%M"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # git が使えない環境では、このファイルの更新時刻で代用する
    import datetime

    stamp = datetime.datetime.fromtimestamp(Path(__file__).stat().st_mtime)
    return stamp.strftime("%m/%d %H:%M")


def build_app(directory: Path, prefill: bool) -> FastAPI:
    app = FastAPI(title="正解ラベル入力", docs_url=None, redoc_url=None)

    # OCRは1枚あたり数秒かかるため、結果を覚えておき、次の分は裏で先に処理する。
    #
    # _running は「いま処理中のファイル」。これが無いと、先読みが終わる前に
    # 利用者がその名刺へ進んだとき、同じ画像を2回OCRしてしまう
    # （実測：3枚に対してOCRが4回走っていた）。CPUを二重に使うだけでなく、
    # 表示が出るまでの待ちも長くなる。
    _ocr_cache: dict[str, tuple[dict[str, str], str | None]] = {}
    _running: dict[str, threading.Event] = {}
    _cache_lock = threading.Lock()

    def image_files() -> list[Path]:
        return sorted(
            p for p in directory.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        )

    def label_path(image: Path) -> Path:
        return image.with_suffix(".json")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return HTMLResponse(PAGE)

    @app.get("/api/files")
    def api_files() -> JSONResponse:
        rows = []
        for path in image_files():
            saved = label_path(path)
            rows.append({
                "name": path.name,
                "stem": path.stem,
                "labeled": saved.exists(),
            })
        return JSONResponse({
            "directory": str(directory),
            "version": _version(),
            "fields": [
                {"key": key, "label": LABELS[key], "hint": HINTS.get(key, "")}
                for key in FIELD_KEYS
            ],
            "files": rows,
            "prefill": prefill,
        })

    @app.get("/api/image/{name}")
    def api_image(name: str):
        path = directory / name
        if not path.is_file() or path.parent.resolve() != directory.resolve():
            return JSONResponse({"error": "見つかりません"}, status_code=404)
        if path.suffix.lower() in (".pdf", ".heic", ".tif", ".tiff"):
            # ブラウザが表示できない形式はJPEGに変換して返す。
            # 失敗しても壊れた画像アイコンだけを出さず、理由を返す
            # （実テストで1枚だけ画像が出ず、原因が分からない状態になった）。
            import io
            import traceback

            from fastapi.responses import Response

            from bcards.services.images import load_pages

            try:
                # 1枚目しか使わないので1ページだけ読む。全ページ読むと、
                # 読み取り機がまとめて出す複数ページPDFで数百MB〜1GBを使い、
                # 以降の名刺の画像が出なくなる（実テストで発生）。
                pages = load_pages(path.read_bytes(), path.name, limit=1)
                if not pages:
                    raise ValueError("ページがありません")
                buffer = io.BytesIO()
                pages[0].image.save(buffer, format="JPEG", quality=90)
            except Exception as exc:  # noqa: BLE001 - 画面に理由を出すため握る
                traceback.print_exc()
                print(f"[画像を表示できません] {path.name}: {exc}")
                return JSONResponse(
                    {"error": f"画像を表示できません: {type(exc).__name__}: {exc}"},
                    status_code=415,
                )
            return Response(content=buffer.getvalue(), media_type="image/jpeg")
        return FileResponse(path)

    @app.get("/api/label/{name}")
    def api_get_label(name: str, draft: str | None = None) -> JSONResponse:
        path = directory / name
        saved = label_path(path)
        if saved.exists():
            data = json.loads(saved.read_text(encoding="utf-8"))
            return JSONResponse({
                "values": {k: str(data.get(k, "") or "") for k in FIELD_KEYS},
                "source": "保存済み",
                "kind": "saved",
                "prefilled": [],
            })

        use_draft = prefill if draft is None else (draft == "1")
        if not use_draft:
            return JSONResponse({
                "values": {key: "" for key in FIELD_KEYS},
                "source": "未入力",
                "kind": "empty",
                "prefilled": [],
            })

        values, error, ocr_text = _ocr_draft(path)
        _warm_next(name)
        if error:
            return JSONResponse({
                "values": {key: "" for key in FIELD_KEYS},
                "source": f"OCRを使えませんでした: {error}",
                "kind": "error",
                "prefilled": [],
                "ocr_text": "",
            })
        filled = [k for k, v in values.items() if v]
        return JSONResponse({
            "values": values,
            "source": "OCRの下書きです。黄色の欄は未確認です。画像と見比べて直してください。",
            "kind": "draft",
            "prefilled": filled,
            "ocr_text": ocr_text,
        })

    def _ocr_draft(path: Path) -> tuple[dict[str, str], str | None, str]:
        """OCRで下書きを作る。結果はファイルごとにキャッシュする。

        戻り値の3つ目は**OCRが読んだ文字そのもの**。項目が空のとき、
        読めていないのか取り出せていないのかは、これを見ないと切り分けられない。
        画面に出しておくことで、報告の往復を減らす。
        """
        while True:
            with _cache_lock:
                hit = _ocr_cache.get(path.name)
                if hit is not None:
                    return hit
                running = _running.get(path.name)
                if running is None:
                    # 自分が処理する。他は待つ
                    _running[path.name] = threading.Event()
                    break
            # 他が処理中。終わるまで待ってからキャッシュを見に戻る。
            # 待ち手が落ちても止まらないよう上限を置く（超えたら自分で処理し直す）。
            running.wait(timeout=180)

        # どの工程で落ちたかを残す。工程名が無いと、画像の読み込みなのか
        # OCRなのか切り分けられず、原因の報告だけで何往復もすることになる。
        step = "準備"
        try:
            try:
                from bcards.services.images import process_file
                from bcards.services.ocr import recognize_card

                step = "画像の読み込みと補正"
                # 使うのは cards[0] だけ。1ページに絞らないと、複数ページPDFで
                # ページごとに補正まで走り、メモリと時間を無駄に使う
                # （実測：20ページで 1.17GB / 23秒 → 1ページなら 78MB / 1.2秒）。
                cards = process_file(path.read_bytes(), path.name, page_limit=1)
                if not cards:
                    raise RuntimeError("画像を1枚も取り出せませんでした")

                step = "OCR"
                output, parsed = recognize_card(cards[0].ocr_image)
                values = {key: str(parsed["fields"].get(key, "") or "") for key in FIELD_KEYS}
                text = output.text if output is not None else ""
                result = (values, None, text)
            except Exception as exc:
                # 画面には要約しか出せないので、原因を追えるようにコンソールへ全文を出す
                print(f"\n[{path.name}] {step}で失敗しました", file=sys.stderr)
                traceback.print_exc()
                detail = str(exc) or exc.__class__.__name__
                # 失敗はキャッシュしない。一時的な失敗（メモリ不足、他プロセスとの
                # 競合など）を覚え込むと、原因を直しても画面を開き直すまで
                # 失敗したままになる。次に開いたときにやり直せるようにする。
                return {key: "" for key in FIELD_KEYS}, f"{step}で失敗（{detail}）", ""

            with _cache_lock:
                _ocr_cache[path.name] = result
            return result
        finally:
            # 成功・失敗どちらでも待ち手を解放する。ここを漏らすと、
            # 待っている側が上限（180秒）まで固まる。
            with _cache_lock:
                finished = _running.pop(path.name, None)
            if finished is not None:
                finished.set()

    def _warm_next(name: str) -> None:
        """次の名刺のOCRを裏で先に済ませておく（1枚あたり数秒かかるため）。"""
        names = [p.name for p in image_files()]
        if name not in names:
            return
        index = names.index(name)
        for nxt in names[index + 1 : index + 3]:
            target = directory / nxt
            with _cache_lock:
                if nxt in _ocr_cache:
                    continue
            threading.Thread(target=_ocr_draft, args=(target,), daemon=True).start()

    @app.post("/api/label/{name}")
    async def api_save_label(name: str, request: Request) -> JSONResponse:
        path = directory / name
        if not path.is_file():
            return JSONResponse({"error": "見つかりません"}, status_code=404)
        payload = await request.json()
        values = {key: str(payload.get(key, "") or "").strip() for key in FIELD_KEYS}

        # OCRの下書きをそのまま採用した項目を記録する。
        # 精度を測るとき、正解がOCR由来だと数値が実際より良く出るため、
        # あとから「どれを人が確認したか」を追えるようにしておく。
        unverified = [k for k in payload.get("_unverified", []) if k in FIELD_KEYS]
        record: dict = dict(values)
        if unverified:
            record["_unverified"] = unverified
        label_path(path).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return JSONResponse({"ok": True, "unverified": len(unverified)})

    @app.delete("/api/label/{name}")
    def api_delete_label(name: str) -> JSONResponse:
        path = label_path(directory / name)
        if path.exists():
            path.unlink()
        return JSONResponse({"ok": True})

    @app.post("/api/not-a-card/{name}")
    def api_not_a_card(name: str) -> JSONResponse:
        """名刺でないものを一覧から外す。

        仕分けは名刺と判定したファイルをこのフォルダへ**コピー**するため、
        取りこぼした領収書などは、仕分けをやり直しても残り続ける。
        入力する人が自分で外せないと、毎回その1枚から始まることになる。

        消さずに not-cards/ へ移す。仕分けの精度を測り直すときの材料になるため。
        """
        source = directory / name
        if not source.is_file() or source.parent.resolve() != directory.resolve():
            return JSONResponse({"error": "見つかりません"}, status_code=404)

        destination = directory / "not-cards"
        destination.mkdir(exist_ok=True)
        moved = []
        # 画像だけでなく、ラベルやOCRテキストなど同じ名前の付随ファイルもまとめて移す
        for sibling in sorted(directory.glob(f"{glob.escape(source.stem)}.*")):
            if not sibling.is_file():
                continue
            target = destination / sibling.name
            if target.exists():
                target.unlink()
            sibling.rename(target)
            moved.append(sibling.name)

        with _cache_lock:
            _ocr_cache.pop(name, None)
        return JSONResponse({"ok": True, "moved": moved, "to": str(destination)})

    return app


PAGE = """
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>正解ラベル入力</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, "Hiragino Sans", "Meiryo", sans-serif;
         background: #f4f5f7; color: #1a1a1a; }
  header { background: #1f5fa9; color: #fff; padding: 10px 16px; display: flex;
           align-items: center; gap: 16px; flex-wrap: wrap; position: sticky; top: 0; z-index: 10; }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  .progress-text { font-size: 13px; opacity: .9; }
  .bar { flex: 1; min-width: 120px; height: 6px; background: rgba(255,255,255,.3); border-radius: 3px; }
  .bar > div { height: 100%; background: #7ec8ff; border-radius: 3px; width: 0; transition: width .2s; }
  main { display: grid; grid-template-columns: minmax(320px, 1fr) minmax(360px, 480px);
         gap: 16px; padding: 16px; align-items: start; }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  .panel { background: #fff; border: 1px solid #dfe3e8; border-radius: 8px; padding: 14px; }
  .imgwrap { position: sticky; top: 64px; }
  .imgwrap img { width: 100%; border: 1px solid #dfe3e8; border-radius: 6px; cursor: zoom-in; background:#fff; }
  .imgwrap img.zoom { position: fixed; inset: 8px; width: auto; height: auto;
                      max-width: calc(100vw - 16px); max-height: calc(100vh - 16px);
                      margin: auto; z-index: 100; cursor: zoom-out; box-shadow: 0 8px 40px rgba(0,0,0,.4); }
  .filename { font-size: 13px; color: #555; margin: 0 0 8px; word-break: break-all; }
  .ocrbox { margin-top: 10px; font-size: 13px; }
  .ocrbox summary { cursor: pointer; color: #555; }
  .ocrbox pre { background: #f6f7f9; border: 1px solid #e0e3e8; border-radius: 4px;
                padding: 8px; margin: 6px 0 0; max-height: 260px; overflow: auto;
                white-space: pre-wrap; word-break: break-all; font-size: 12px; }
  .imgerror:empty { display: none; }
  .imgerror { font-size: 13px; padding: 8px 10px; border-radius: 4px; margin: 8px 0;
              background: #fff4e5; border: 1px solid #ffd8a8; color: #8a5300; }
  .source { font-size: 12px; padding: 6px 8px; border-radius: 4px; margin-bottom: 10px; }
  .source.warn { background: #fff4e5; border: 1px solid #ffd8a8; color: #8a5300; }
  .source.plain { background: #f0f2f5; color: #555; }
  .field { margin-bottom: 10px; }
  .field label { display: block; font-size: 12px; color: #444; margin-bottom: 3px; font-weight: 600; }
  .field input { width: 100%; padding: 7px 9px; font-size: 14px; border: 1px solid #c8ccd4;
                 border-radius: 4px; font-family: inherit; }
  .field input:focus { outline: 2px solid #1f5fa9; outline-offset: -1px; border-color: #1f5fa9; }
  .field input.draft { background: #fff8e1; border-color: #e0b64a; }
  .field.unverified label::after { content: " 未確認"; color: #8a5300; font-weight: 400; }
  .toggle { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #fff; }
  .toggle input { width: auto; }
  .field .hint { font-size: 11px; color: #888; margin-top: 2px; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  /* 入力欄が14項目あるため、操作ボタンは下端に貼り付けて常に見えるようにする。
     以前は最下部にあり、スクロールしないと見えなかった。 */
  .actions { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; align-items: center;
             position: sticky; bottom: 0; background: #fff; padding: 10px 0;
             border-top: 1px solid #e3e5e8; z-index: 5; }
  .notcard-row { margin: 12px 0 0; }
  .notcard-row button { font-size: 12px; color: #8a4b00; border-color: #e0c49a; background: #fff8ef; }
  .notcard-row button:hover { background: #f6e7d2; }
  button { padding: 9px 14px; font-size: 14px; border-radius: 5px; border: 1px solid #c8ccd4;
           background: #fff; cursor: pointer; font-family: inherit; }
  button.primary { background: #1f5fa9; color: #fff; border-color: #1f5fa9; font-weight: 600; }
  button:disabled { opacity: .45; cursor: default; }
  .files { max-height: 260px; overflow-y: auto; border: 1px solid #dfe3e8; border-radius: 6px; }
  .files button { display: block; width: 100%; text-align: left; border: 0; border-bottom: 1px solid #eef0f3;
                  border-radius: 0; padding: 7px 10px; font-size: 13px; background: #fff; }
  .files button.current { background: #e8f1fb; font-weight: 600; }
  .files button .tick { color: #2f855a; margin-right: 5px; }
  .files button .todo { color: #bbb; margin-right: 5px; }
  .saved { font-size: 13px; color: #2f855a; }
  .kbd { font-size: 11px; color: #666; margin-top: 10px; line-height: 1.7; }
  .kbd code { background: #eef0f3; padding: 1px 5px; border-radius: 3px; }
</style>
</head>
<body>
<header>
  <h1>正解ラベル入力</h1>
  <span class="progress-text" id="progress">読み込み中…</span>
  <div class="bar"><div id="bar"></div></div>
  <label class="toggle"><input type="checkbox" id="draft"> OCRで下書きする</label>
  <span class="progress-text" id="version" title="この画面の版。更新したのに変わらなければ、取得できていません"></span>
</header>
<main>
  <div>
    <div class="panel imgwrap">
      <p class="filename" id="filename">—</p>
      <img id="image" alt="名刺画像" onclick="this.classList.toggle('zoom')"
           onerror="showImageError()">
      <div id="imgerror" class="imgerror"></div>
      <details id="ocrbox" class="ocrbox">
        <summary>OCRが読んだ文字を見る（項目が空のときの手がかり）</summary>
        <pre id="ocrtext"></pre>
      </details>
      <p class="kbd">画像をクリックすると拡大します。</p>
      <!-- 「名刺ではない」は画像を見た時点で判断するので、画像のすぐ下に置く。
           入力欄の下（14項目ぶん下）だと画面外で気づけない。 -->
      <p class="notcard-row">
        <button type="button" id="notcard">これは名刺ではない（一覧から外す）</button>
      </p>
    </div>
  </div>
  <div>
    <div class="panel">
      <div class="source plain" id="source">—</div>
      <form id="form" autocomplete="off"></form>
      <div class="actions">
        <button type="button" id="prev">← 前へ</button>
        <button type="button" class="primary" id="next">保存して次へ →</button>
        <button type="button" id="skip">スキップ</button>
        <span class="saved" id="saved"></span>
        <span class="small muted" id="unverified"></span>
      </div>
      <p class="kbd">
        <code>Ctrl</code>+<code>Enter</code> 保存して次へ ／
        <code>Alt</code>+<code>←</code> <code>→</code> 前後の名刺へ<br>
        記載の無い項目は空欄のままにしてください（空欄も正解として扱われます）。
      </p>
    </div>
    <div class="panel" style="margin-top:16px">
      <div class="files" id="files"></div>
    </div>
  </div>
</main>
<script>
let state = { files: [], fields: [], index: 0, prefill: false, unverified: new Set(), timer: null };

async function boot() {
  const meta = await (await fetch('/api/files')).json();
  state.fields = meta.fields;
  state.files = meta.files;
  state.prefill = meta.prefill;
  document.getElementById('version').textContent = '版 ' + (meta.version || '不明');
  const draftBox = document.getElementById('draft');
  draftBox.checked = meta.prefill;
  draftBox.onchange = () => show(state.index);
  if (!state.files.length) {
    document.getElementById('progress').textContent = '画像が見つかりません: ' + meta.directory;
    return;
  }
  buildForm();
  const firstTodo = state.files.findIndex(f => !f.labeled);
  state.index = firstTodo >= 0 ? firstTodo : 0;
  await show(state.index);
}

function buildForm() {
  const form = document.getElementById('form');
  const pairs = [['last_name','first_name'], ['last_name_kana','first_name_kana']];
  const paired = new Set(pairs.flat());
  let html = '';
  for (const [a, b] of pairs) {
    html += '<div class="row2">' + [a, b].map(k => fieldHtml(k)).join('') + '</div>';
  }
  for (const f of state.fields) {
    if (!paired.has(f.key)) html += fieldHtml(f.key);
  }
  form.innerHTML = html;
}

function fieldHtml(key) {
  const f = state.fields.find(x => x.key === key);
  return `<div class="field">
    <label for="f_${f.key}">${f.label}</label>
    <input id="f_${f.key}" name="${f.key}" type="text"
           oninput="confirmField('${f.key}')" onfocus="confirmField('${f.key}')">
    ${f.hint ? `<div class="hint">${f.hint}</div>` : ''}
  </div>`;
}

// 画像が出せないときは、壊れたアイコンではなく理由を出す。
//
// 「この1枚だけの問題」と決めつけないこと。サーバーが落ちていると以降の名刺も
// すべて画像が出ないが、実テストではその場合も「この1枚だけ」と表示していたため、
// 原因を1枚目のファイルだと見誤ることになった。両者を区別して出す。
async function showImageError() {
  const box = document.getElementById('imgerror');
  const file = state.files[state.index];
  box.textContent = '画像を表示できません。原因を調べています…';

  let reason = null;
  try {
    const res = await fetch('/api/image/' + encodeURIComponent(file.name));
    const body = await res.json();
    if (body && body.error) reason = body.error;
  } catch (e) { /* サーバーが応答していない可能性。下で確かめる */ }

  if (reason) {
    box.textContent = reason + '（この1枚だけの問題です。入力は続けられます）';
    return;
  }

  try {
    const alive = await fetch('/api/files', { cache: 'no-store' });
    if (alive.ok) {
      box.textContent = '画像を表示できません（この1枚だけの問題です。入力は続けられます）';
      return;
    }
  } catch (e) { /* 落ちている */ }

  box.innerHTML = '<b>サーバーが応答していません。</b>'
    + 'このあとの名刺もすべて画像が出ません。'
    + '「ラベル付けを始める」の黒い画面を閉じて、もう一度開いてください。'
    + '（黒い画面の最後の行が原因の手がかりです）';
}

async function show(i) {
  state.index = i;
  const file = state.files[i];
  document.getElementById('filename').textContent = file.name;
  document.getElementById('imgerror').textContent = '';
  document.getElementById('ocrtext').textContent = '';
  document.getElementById('image').src = '/api/image/' + encodeURIComponent(file.name);
  document.getElementById('image').classList.remove('zoom');
  document.getElementById('saved').textContent = '';
  clearMarks();

  // 前の名刺の値を消してから読み込む。消さないと、OCRを待っている間に
  // 前の名刺の値が入ったままになり、そのまま保存できてしまう（実テストで発生）。
  for (const f of state.fields) {
    const input = document.getElementById('f_' + f.key);
    if (input) input.value = '';
  }
  // 待たせるのは「保存して次へ」だけ。スキップと「前へ」はOCRの結果に
  // 関係がないので、いつでも押せるようにしておく（OCRが返ってこないときに
  // 先へ進めなくなり、実テストで手が止まった）。
  document.getElementById('next').disabled = true;

  // 枚数・進捗・一覧はOCRの結果に依らないので、待たずに先に出す。
  // 以前はOCRのあとに描いていたため、数秒間ヘッダが「読み込み中…」のままだった。
  document.getElementById('prev').disabled = i === 0;
  renderProgress();
  renderFiles();

  const useDraft = document.getElementById('draft').checked ? '1' : '0';
  const src = document.getElementById('source');
  src.textContent = useDraft === '1' ? 'OCRで下書きしています…' : '';
  src.className = 'source plain';

  // 経過を出す。止まっているのか動いているのか分からないと手が止まる。
  // 20秒を超えたら、待たずに進めることを伝える。
  if (state.timer) clearInterval(state.timer);
  if (useDraft === '1') {
    const started = Date.now();
    state.timer = setInterval(() => {
      if (state.index !== i) { clearInterval(state.timer); return; }
      const seconds = Math.round((Date.now() - started) / 1000);
      src.textContent = seconds >= 20
        ? `OCRで下書きしています…（${seconds}秒）　時間がかかっています。「スキップ」で次へ進めます`
        : `OCRで下書きしています…（${seconds}秒）`;
    }, 1000);
  }

  const url = '/api/label/' + encodeURIComponent(file.name) + '?draft=' + useDraft;
  let data;
  try {
    data = await (await fetch(url)).json();
  } catch (e) {
    // 取れなくても手を止めない。空欄のまま入力できるようにする
    if (state.index !== i) return;
    document.getElementById('next').disabled = false;
    src.textContent = 'OCRの結果を取得できませんでした。空欄から入力してください。';
    src.className = 'source warn';
    return;
  }
  if (state.index !== i) return;   // 待っている間に別の名刺へ移った
  document.getElementById('next').disabled = false;

  for (const f of state.fields) {
    document.getElementById('f_' + f.key).value = data.values[f.key] || '';
  }
  // OCRが入れた欄は「未確認」として色を付ける。触れば消える
  state.unverified = new Set(data.prefilled || []);
  for (const key of state.unverified) mark(key, true);

  if (state.timer) clearInterval(state.timer);
  document.getElementById('ocrtext').textContent =
      data.ocr_text || '（OCRの結果はありません）';
  src.textContent = data.source;
  src.className = 'source ' + (data.kind === 'draft' || data.kind === 'error' ? 'warn' : 'plain');

  renderProgress();
  renderFiles();
  renderUnverified();
  const first = document.getElementById('f_' + state.fields[0].key);
  if (first) first.focus();
}

function mark(key, on) {
  const input = document.getElementById('f_' + key);
  if (!input) return;
  input.classList.toggle('draft', on);
  input.closest('.field').classList.toggle('unverified', on);
}

function clearMarks() {
  for (const f of state.fields) mark(f.key, false);
  state.unverified = new Set();
}

function confirmField(key) {
  if (!state.unverified.has(key)) return;
  state.unverified.delete(key);
  mark(key, false);
  renderUnverified();
}

function renderUnverified() {
  const n = state.unverified.size;
  document.getElementById('unverified').textContent =
    n ? `未確認 ${n} 項目（黄色の欄）` : '';
}

function renderProgress() {
  const done = state.files.filter(f => f.labeled).length;
  document.getElementById('progress').textContent =
    `${state.index + 1} / ${state.files.length} 枚目　（入力済み ${done} 枚）`;
  document.getElementById('bar').style.width = (done / state.files.length * 100) + '%';
}

function renderFiles() {
  document.getElementById('files').innerHTML = state.files.map((f, i) =>
    `<button type="button" onclick="show(${i})" class="${i === state.index ? 'current' : ''}">
       <span class="${f.labeled ? 'tick' : 'todo'}">${f.labeled ? '✓' : '○'}</span>${f.name}
     </button>`).join('');
}

async function save() {
  const file = state.files[state.index];
  const body = { _unverified: [...state.unverified] };
  for (const f of state.fields) body[f.key] = document.getElementById('f_' + f.key).value;
  await fetch('/api/label/' + encodeURIComponent(file.name), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  file.labeled = true;
  document.getElementById('saved').textContent = '保存しました';
  renderProgress();
  renderFiles();
}

async function saveAndNext() {
  await save();
  if (state.index < state.files.length - 1) await show(state.index + 1);
  else document.getElementById('saved').textContent = 'すべて入力しました';
}

document.getElementById('next').onclick = saveAndNext;
document.getElementById('prev').onclick = () => show(Math.max(0, state.index - 1));
document.getElementById('skip').onclick = () => {
  if (state.index < state.files.length - 1) show(state.index + 1);
};
// 仕分けが取りこぼした領収書などを一覧から外す。消さずに not-cards/ へ移す。
document.getElementById('notcard').onclick = async () => {
  const file = state.files[state.index];
  if (!confirm(file.name + ' を「名刺ではない」として一覧から外します。\\n\\n'
             + 'ファイルは消さず、not-cards フォルダへ移します。')) return;
  const res = await fetch('/api/not-a-card/' + encodeURIComponent(file.name), {method: 'POST'});
  if (!res.ok) { alert('外せませんでした。'); return; }
  const at = state.index;
  const meta = await (await fetch('/api/files')).json();
  state.files = meta.files;
  if (!state.files.length) {
    document.getElementById('progress').textContent = '画像が残っていません';
    return;
  }
  await show(Math.min(at, state.files.length - 1));
  document.getElementById('saved').textContent = '一覧から外しました';
};
document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); saveAndNext(); }
  if (e.altKey && e.key === 'ArrowRight') { e.preventDefault(); if (state.index < state.files.length - 1) show(state.index + 1); }
  if (e.altKey && e.key === 'ArrowLeft') { e.preventDefault(); if (state.index > 0) show(state.index - 1); }
});
boot();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", help="名刺画像の入っているフォルダ")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument(
        "--no-prefill",
        action="store_true",
        help="OCRの下書きを使わず、空欄から入力する（測定用の正解を厳密に作る場合）",
    )
    parser.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    args = parser.parse_args()

    directory = Path(args.directory).expanduser().resolve()
    if not directory.is_dir():
        print(f"フォルダが見つかりません: {directory}", file=sys.stderr)
        return 2

    images = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    if not images:
        print(f"画像が見つかりません: {directory}", file=sys.stderr)
        return 2

    labeled = sum(1 for p in images if p.with_suffix(".json").exists())
    print(f"対象: {directory}")
    print(f"画像 {len(images)} 枚（入力済み {labeled} 枚 / 残り {len(images) - labeled} 枚）")
    if args.no_prefill:
        print("\n--no-prefill 指定：空欄から入力します。\n")
    else:
        print("\nOCRが下書きを入れます。黄色い欄は「未確認」です。")
        print("  画像と見比べて直してください。触れば色が消えます。")
        print("  下書きを使わずに入力する場合は --no-prefill を付けてください。\n")
    url = f"http://127.0.0.1:{args.port}/"
    print(f"\n入力画面: {url}")
    print("終了するには、この画面で Ctrl-C を押すか、ウィンドウを閉じてください。")

    if not args.no_browser:
        # サーバーが起動してから開く。起動前に開くと「接続できません」になる
        import threading
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # 先に自分で束縛して、使えないポートならここで分かりやすく知らせる。
    # uvicorn に任せると内部で捕捉されてしまい、原因が伝わりにくい。
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", args.port))
    except OSError as exc:
        print(
            f"\nポート {args.port} は使用中です（{exc}）。\n"
            f"  すでに入力画面が起動していませんか。その場合はブラウザで {url} を開いてください。\n"
            f"  別のポートを使うなら --port 8101 のように指定します。",
            file=sys.stderr,
        )
        return 1
    finally:
        probe.close()

    import uvicorn

    uvicorn.run(
        build_app(directory, not args.no_prefill),
        host="127.0.0.1", port=args.port, log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
