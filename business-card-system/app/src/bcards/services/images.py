"""画像の読み込み・補正・分割（要件§4）。

対応形式：JPEG / JPG / PNG / PDF / HEIC / TIFF
HEIC・TIFF はサーバー側で JPEG に変換して処理する。
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps

from ..config import settings
from . import orientation

try:  # HEIC 対応
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except Exception:  # pragma: no cover - 環境依存
    HEIC_SUPPORTED = False

try:  # PDF 対応
    import pypdfium2

    PDF_SUPPORTED = True
except Exception:  # pragma: no cover - 環境依存
    PDF_SUPPORTED = False


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf", ".heic", ".heif", ".tif", ".tiff"}

MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


class UnsupportedFileError(ValueError):
    pass


@dataclass
class LoadedPage:
    image: Image.Image
    page_no: int | None
    original_mime: str


@dataclass
class ProcessedCard:
    """1枚の名刺として切り出された画像と、その処理結果。

    image     : 表示用（明るさ・影の補正まで行ったもの。人が見やすい）
    ocr_image : OCR用（切り出しと傾き補正のみ。強い補正はOCR精度を下げるため行わない）
                原本として保存するのもこちら。
    """

    image: Image.Image
    ocr_image: Image.Image
    page_no: int | None
    split_index: int | None
    original_mime: str
    corrections: dict[str, Any] = field(default_factory=dict)
    warnings: dict[str, Any] = field(default_factory=dict)


def extension_of(filename: str) -> str:
    name = (filename or "").lower()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def load_pages(data: bytes, filename: str, *, limit: int | None = None) -> list[LoadedPage]:
    """アップロードされたファイルをページ単位の画像に展開する。

    `limit` を渡すと、先頭からその枚数だけ展開して残りは読まない。

    ページの展開は**1ページあたり15MB前後**のメモリを使う（名刺1枚を
    200dpiで描くと 1050×640×3 バイト、A4なら約11MB）。1枚目しか使わない
    呼び出しで全ページを展開すると、複数ページのPDF（読み取り機が
    まとめて出す形）で数百MB〜1GBを消費する。実測では20ページのPDF
    （229KB）で `process_file` が 1.17GB を使っていた。
    """
    ext = extension_of(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(
            f"未対応のファイル形式です（{ext or '拡張子なし'}）。JPEG/PNG/PDF/HEIC/TIFF に対応しています。"
        )
    mime = MIME_BY_EXT.get(ext, "application/octet-stream")

    if ext == ".pdf":
        if not PDF_SUPPORTED:
            raise UnsupportedFileError("PDFの読み込みに必要なライブラリが利用できません。")
        return _load_pdf(data, mime, limit)

    if ext in (".heic", ".heif") and not HEIC_SUPPORTED:
        raise UnsupportedFileError("HEICの読み込みに必要なライブラリが利用できません。")

    image = Image.open(io.BytesIO(data))
    pages: list[LoadedPage] = []
    if ext in (".tif", ".tiff") and getattr(image, "n_frames", 1) > 1:
        count = image.n_frames if limit is None else min(image.n_frames, limit)
        for index in range(count):  # 複数ページTIFF
            image.seek(index)
            pages.append(LoadedPage(_to_rgb(image.copy()), index + 1, mime))
    else:
        pages.append(LoadedPage(_to_rgb(image), None, mime))
    return pages


def _load_pdf(data: bytes, mime: str, limit: int | None = None) -> list[LoadedPage]:
    pdf = pypdfium2.PdfDocument(data)
    pages: list[LoadedPage] = []
    try:
        count = len(pdf) if limit is None else min(len(pdf), limit)
        for index in range(count):
            page = pdf[index]
            # 名刺のOCRに耐える解像度（およそ200dpi相当）で描画する
            bitmap = page.render(scale=200 / 72)
            pages.append(LoadedPage(_to_rgb(bitmap.to_pil()), index + 1, mime))
    finally:
        pdf.close()
    return pages


def _to_rgb(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)  # スマホ撮影のEXIF回転を反映
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image


# --------------------------------------------------------------------------
# 名刺領域の検出と補正
# --------------------------------------------------------------------------


def _pil_to_cv(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def _cv_to_pil(array: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(array, cv2.COLOR_BGR2RGB))


def detect_card_quads(image: Image.Image, max_cards: int = 6) -> list[np.ndarray]:
    """画像内の名刺らしい四角形を検出する（複数名刺の分割候補、要件§4）。"""
    src = _pil_to_cv(image)
    height, width = src.shape[:2]
    area_total = float(height * width)

    gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    edges = cv2.Canny(gray, 40, 140)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    quads: list[tuple[float, np.ndarray]] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < area_total * 0.04 or area > area_total * 0.98:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        quad = approx.reshape(4, 2).astype("float32")
        ratio = _aspect_ratio(quad)
        if ratio and not (1.2 <= ratio <= 2.4):  # 名刺の縦横比（91x55mm ≒ 1.65）から大きく外れるものは除外
            continue
        quads.append((area, quad))

    quads.sort(key=lambda x: x[0], reverse=True)
    selected: list[np.ndarray] = []
    for _, quad in quads:
        if all(not _overlaps(quad, chosen) for chosen in selected):
            selected.append(quad)
        if len(selected) >= max_cards:
            break
    return selected


def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # 左上
    rect[2] = pts[np.argmax(s)]  # 右下
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # 右上
    rect[3] = pts[np.argmax(diff)]  # 左下
    return rect


def _aspect_ratio(quad: np.ndarray) -> float | None:
    rect = _order_points(quad)
    (tl, tr, br, bl) = rect
    width = max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))
    height = max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))
    if width <= 0 or height <= 0:
        return None
    return max(width, height) / min(width, height)


def _overlaps(a: np.ndarray, b: np.ndarray) -> bool:
    ax1, ay1 = a.min(axis=0)
    ax2, ay2 = a.max(axis=0)
    bx1, by1 = b.min(axis=0)
    bx2, by2 = b.max(axis=0)
    inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = inter_w * inter_h
    area_a = (ax2 - ax1) * (ay2 - ay1)
    return area_a > 0 and inter / area_a > 0.3


def warp_quad(image: Image.Image, quad: np.ndarray) -> Image.Image:
    """台形補正（斜め撮影の補正、要件§4）。"""
    src = _pil_to_cv(image)
    rect = _order_points(quad)
    (tl, tr, br, bl) = rect
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    width, height = max(width, 1), max(height, 1)
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
    matrix = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(src, matrix, (width, height))
    return _cv_to_pil(warped)


def deskew(image: Image.Image, max_angle: float = 10.0, min_angle: float = 1.5) -> tuple[Image.Image, float]:
    """傾きを回転補正する（要件§4）。

    min_angle 未満の傾きは補正しない。わずかな回転でも再サンプリングで
    文字がぼやけ、OCR精度が下がることをPoCで確認したため
    （docs: ocr-poc-report.md）。
    """
    src = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(src, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=100, minLineLength=src.shape[1] // 3, maxLineGap=20)
    if lines is None:
        return image, 0.0
    angles = []
    # OpenCV のバージョンにより (N, 1, 4) / (N, 4) のどちらも返るため揃える
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if abs(angle) <= max_angle:
            angles.append(angle)
    if not angles:
        return image, 0.0
    angle = float(np.median(angles))
    if abs(angle) < min_angle:
        return image, 0.0
    return image.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255)), angle


def orient_landscape(image: Image.Image) -> tuple[Image.Image, bool]:
    """縦長に写っている名刺を横長に回転する。"""
    if image.height > image.width * 1.2:
        return image.rotate(-90, expand=True), True
    return image, False


def enhance(image: Image.Image) -> tuple[Image.Image, dict[str, Any]]:
    """明るさ・コントラスト補正と影の軽減（要件§4）。"""
    src = _pil_to_cv(image)
    lab = cv2.cvtColor(src, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)

    before_mean = float(lightness.mean())
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lightness = clahe.apply(lightness)

    # 影の軽減：大きなカーネルで推定した背景で割り戻す
    background = cv2.medianBlur(lightness, 31)
    background = np.where(background == 0, 1, background)
    normalized = np.clip((lightness.astype(np.float32) / background.astype(np.float32)) * 200, 0, 255)
    lightness = cv2.addWeighted(lightness, 0.6, normalized.astype(np.uint8), 0.4, 0)

    merged = cv2.merge((lightness, a, b))
    result = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
    return _cv_to_pil(result), {
        "brightness_before": round(before_mean, 1),
        "brightness_after": round(float(lightness.mean()), 1),
    }


def quality_report(image: Image.Image) -> dict[str, Any]:
    """解像度不足・ピンぼけの警告（要件§4）。"""
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    warnings: dict[str, Any] = {
        "blur_score": round(blur_score, 1),
        "width": image.width,
        "height": image.height,
    }
    messages = []
    if max(image.width, image.height) < settings.min_card_width_px:
        messages.append(
            f"解像度が不足しています（長辺 {max(image.width, image.height)}px）。"
            f"{settings.min_card_width_px}px 以上を推奨します。"
        )
    if blur_score < settings.blur_threshold:
        messages.append("画像がぼやけています。ピントを合わせて撮り直すと認識精度が上がります。")
    warnings["messages"] = messages
    return warnings


def process_file(
    data: bytes, filename: str, *, correct: bool = True, page_limit: int | None = None
) -> list[ProcessedCard]:
    """アップロードファイル1件を、名刺1枚ごとの補正済み画像に変換する。

    `page_limit` を渡すと、先頭からその枚数のページだけ処理する。1枚目しか
    使わない呼び出しでは必ず渡すこと（`load_pages` の説明を参照）。
    """
    cards: list[ProcessedCard] = []
    for page in load_pages(data, filename, limit=page_limit):
        quads = detect_card_quads(page.image) if correct else []
        if not quads:
            cards.append(_finish_card(page.image, page, None, correct, detected=False))
            continue
        for index, quad in enumerate(quads):
            warped = warp_quad(page.image, quad)
            split_index = index + 1 if len(quads) > 1 else None
            cards.append(_finish_card(warped, page, split_index, correct, detected=True))
    return cards


def _finish_card(
    image: Image.Image,
    page: LoadedPage,
    split_index: int | None,
    correct: bool,
    *,
    detected: bool,
) -> ProcessedCard:
    """表示用とOCR用の画像を作り分ける。

    PoC（ocr-poc-report.md）で、表示向けの強い補正（明るさ・影の除去、
    縦長から横長への回転）がOCRの項目正答率を10ポイント下げることが分かったため、
    OCRには切り出しと傾き補正のみを適用した画像を渡す。

    縦長から横長への回転は**表示用からも外した**。名刺の形だけを見て回すため、
    正しい向きの縦型名刺（日本語の縦書き名刺）が横倒しになる。実測:

        縦書きの縦型名刺 1240x1754
          → 向きの検出は 0度（正しい。回す必要なし）
          → 縦長なので -90度回される
          → 表示用は 1754x1240 の横倒しになる

    90度単位の回転は `orientation.upright` が字の形から判定して直しており、
    形だけの判定を重ねる必要はない。
    """
    corrections: dict[str, Any] = {"outline_detected": detected, "perspective_corrected": detected}
    ocr_image = image
    if correct:
        # 90度単位の回転を先に直す。deskew が扱うのは数度のズレだけで、
        # 横向きに置いてスキャンした名刺はここで直さないとOCRがほぼ何も読めない。
        ocr_image, turned = orientation.upright(image)
        corrections["orientation_degrees"] = turned

        ocr_image, angle = deskew(ocr_image)
        corrections["deskew_angle"] = round(angle, 2)

        display, brightness = enhance(ocr_image)
        corrections.update(brightness)
        image = display
    return ProcessedCard(
        image=image,
        ocr_image=ocr_image,
        page_no=page.page_no,
        split_index=split_index,
        original_mime=page.original_mime,
        corrections=corrections,
        warnings=quality_report(ocr_image),
    )


# --------------------------------------------------------------------------
# 保存用バリアント（要件§2：原本と表示用を分けて保存）
# --------------------------------------------------------------------------


def to_jpeg_bytes(image: Image.Image, quality: int = 92) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def resized(image: Image.Image, max_edge: int) -> Image.Image:
    if max(image.width, image.height) <= max_edge:
        return image.copy()
    ratio = max_edge / max(image.width, image.height)
    size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
    return image.resize(size, Image.LANCZOS)


def make_variants(
    image: Image.Image, original_image: Image.Image | None = None
) -> dict[str, tuple[bytes, Image.Image]]:
    """原本・表示用・サムネイルを作る（要件§2）。

    original_image を渡した場合はそれを原本として保存する。
    強い補正をかける前の画像を原本にしておくことで、再処理時のOCR精度が落ちない。
    """
    source = original_image if original_image is not None else image
    display = resized(image, settings.display_max_edge)
    thumbnail = resized(image, settings.thumbnail_max_edge)
    return {
        "original": (to_jpeg_bytes(source, quality=95), source),
        "display": (to_jpeg_bytes(display, quality=85), display),
        "thumbnail": (to_jpeg_bytes(thumbnail, quality=80), thumbnail),
    }
