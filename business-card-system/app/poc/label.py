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

## --prefill について

`--prefill` を付けるとOCRの結果を初期値として埋める。入力は速くなるが、
**OCRの誤りをそのまま正解として登録してしまう危険がある**。
その状態で精度を測ると、実際より良い数値が出る。
正確に測りたい場合は付けずに、画像を見て入力すること。
"""

from __future__ import annotations

import argparse
import json
import sys
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


def build_app(directory: Path, prefill: bool) -> FastAPI:
    app = FastAPI(title="正解ラベル入力", docs_url=None, redoc_url=None)

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
            # ブラウザが表示できない形式はJPEGに変換して返す
            import io

            from bcards.services.images import load_pages

            pages = load_pages(path.read_bytes(), path.name)
            buffer = io.BytesIO()
            pages[0].image.save(buffer, format="JPEG", quality=90)
            from fastapi.responses import Response

            return Response(content=buffer.getvalue(), media_type="image/jpeg")
        return FileResponse(path)

    @app.get("/api/label/{name}")
    def api_get_label(name: str) -> JSONResponse:
        path = directory / name
        saved = label_path(path)
        if saved.exists():
            data = json.loads(saved.read_text(encoding="utf-8"))
            return JSONResponse({"values": {k: str(data.get(k, "") or "") for k in FIELD_KEYS},
                                 "source": "保存済み"})

        values = {key: "" for key in FIELD_KEYS}
        source = "未入力"
        if prefill:
            try:
                from bcards.services.images import process_file
                from bcards.services.ocr import recognize_card

                cards = process_file(path.read_bytes(), path.name)
                _output, parsed = recognize_card(cards[0].ocr_image)
                values = {key: str(parsed["fields"].get(key, "") or "") for key in FIELD_KEYS}
                source = "OCRの結果（誤りが含まれます。必ず画像と見比べてください）"
            except Exception as exc:
                source = f"OCRに失敗しました: {exc}"
        return JSONResponse({"values": values, "source": source})

    @app.post("/api/label/{name}")
    async def api_save_label(name: str, request: Request) -> JSONResponse:
        path = directory / name
        if not path.is_file():
            return JSONResponse({"error": "見つかりません"}, status_code=404)
        payload = await request.json()
        values = {key: str(payload.get(key, "") or "").strip() for key in FIELD_KEYS}
        label_path(path).write_text(
            json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return JSONResponse({"ok": True})

    @app.delete("/api/label/{name}")
    def api_delete_label(name: str) -> JSONResponse:
        path = label_path(directory / name)
        if path.exists():
            path.unlink()
        return JSONResponse({"ok": True})

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
  .source { font-size: 12px; padding: 6px 8px; border-radius: 4px; margin-bottom: 10px; }
  .source.warn { background: #fff4e5; border: 1px solid #ffd8a8; color: #8a5300; }
  .source.plain { background: #f0f2f5; color: #555; }
  .field { margin-bottom: 10px; }
  .field label { display: block; font-size: 12px; color: #444; margin-bottom: 3px; font-weight: 600; }
  .field input { width: 100%; padding: 7px 9px; font-size: 14px; border: 1px solid #c8ccd4;
                 border-radius: 4px; font-family: inherit; }
  .field input:focus { outline: 2px solid #1f5fa9; outline-offset: -1px; border-color: #1f5fa9; }
  .field .hint { font-size: 11px; color: #888; margin-top: 2px; }
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .actions { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; align-items: center; }
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
</header>
<main>
  <div>
    <div class="panel imgwrap">
      <p class="filename" id="filename">—</p>
      <img id="image" alt="名刺画像" onclick="this.classList.toggle('zoom')">
      <p class="kbd">画像をクリックすると拡大します。</p>
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
let state = { files: [], fields: [], index: 0, prefill: false };

async function boot() {
  const meta = await (await fetch('/api/files')).json();
  state.fields = meta.fields;
  state.files = meta.files;
  state.prefill = meta.prefill;
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
    <input id="f_${f.key}" name="${f.key}" type="text">
    ${f.hint ? `<div class="hint">${f.hint}</div>` : ''}
  </div>`;
}

async function show(i) {
  state.index = i;
  const file = state.files[i];
  document.getElementById('filename').textContent = file.name;
  document.getElementById('image').src = '/api/image/' + encodeURIComponent(file.name);
  document.getElementById('image').classList.remove('zoom');
  document.getElementById('saved').textContent = '';

  const data = await (await fetch('/api/label/' + encodeURIComponent(file.name))).json();
  for (const f of state.fields) {
    document.getElementById('f_' + f.key).value = data.values[f.key] || '';
  }
  const src = document.getElementById('source');
  src.textContent = data.source;
  src.className = 'source ' + (data.source.startsWith('OCR') ? 'warn' : 'plain');

  document.getElementById('prev').disabled = i === 0;
  renderProgress();
  renderFiles();
  const first = document.getElementById('f_' + state.fields[0].key);
  if (first) first.focus();
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
  const body = {};
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
        "--prefill",
        action="store_true",
        help="OCRの結果を初期値にする（速いが、誤りをそのまま正解にしてしまう危険がある）",
    )
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
    if args.prefill:
        print("\n--prefill 指定：OCRの結果を初期値にします。")
        print("  誤りをそのまま正解として保存すると、精度が実際より良く出ます。")
        print("  必ず画像と見比べてください。\n")
    print(f"ブラウザで http://127.0.0.1:{args.port}/ を開いてください。（Ctrl-C で終了）")

    import uvicorn

    uvicorn.run(build_app(directory, args.prefill), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
