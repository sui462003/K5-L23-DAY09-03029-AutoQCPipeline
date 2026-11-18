"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |
"""
from collections import defaultdict
from pathlib import Path

import yaml

from ..common import ERROR, parse_yolo_line

REMOVE_IMAGE_CODES = {"LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}
DROP_LINE_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}


def fix(ds, issues, cfg):
    fixes: list[dict] = []
    # Chỉ xử lý các lỗi bắt buộc (severity ERROR)
    error_issues = [i for i in issues if i.severity == ERROR]
    if not error_issues:
        return []

    removed_images: set[str] = set()

    # 1. Xóa ảnh + nhãn lỗi nghiêm trọng / trùng / rò rỉ (remove_image)
    for iss in error_issues:
        if iss.code.startswith("DUP_IMAGE_") or iss.code in REMOVE_IMAGE_CODES:
            stem = iss.image
            if stem not in removed_images:
                removed_images.add(stem)
                # Xóa file ảnh trong images_dir
                if ds.images_dir.exists():
                    for p in list(ds.images_dir.glob(f"{stem}.*")):
                        try:
                            p.unlink()
                        except OSError:
                            pass
                # Xóa file nhãn trong labels_dir
                lbl = ds.label_path(stem)
                if lbl.exists():
                    try:
                        lbl.unlink()
                    except OSError:
                        pass
                ds._size_cache.pop(stem, None)
                fixes.append({
                    "image": stem,
                    "line": None,
                    "action": "remove_image",
                    "before": iss.code,
                    "after": "đã xóa ảnh và nhãn",
                })

    # 2. Sửa data.yaml (rename_classes)
    for iss in error_issues:
        if iss.code == "BAD_CLASS_NAME":
            if ds.yaml_path.exists():
                d = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
                before_names = str(d.get("names", ""))
                d["names"] = list(cfg["classes"])
                ds.yaml_path.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True), encoding="utf-8")
                fixes.append({
                    "image": "data.yaml",
                    "line": None,
                    "action": "rename_classes",
                    "before": before_names,
                    "after": str(cfg["classes"]),
                })
            break  # Chỉ sửa 1 lần

    # 3. Ghi nhận ảnh thiếu file nhãn (needs_label) - KHÔNG tạo file nhãn
    seen_missing = set()
    for iss in error_issues:
        if iss.code == "MISSING_LABEL_FILE":
            stem = iss.image
            if stem not in removed_images and stem not in seen_missing:
                seen_missing.add(stem)
                fixes.append({
                    "image": stem,
                    "line": None,
                    "action": "needs_label",
                    "before": "(không có file)",
                    "after": "chuyển người gán",
                })

    # 4. Sửa file nhãn (drop_line, clip_box)
    file_line_issues = defaultdict(lambda: defaultdict(list))
    for iss in error_issues:
        if iss.image in removed_images:
            continue
        if iss.code in DROP_LINE_CODES or iss.code == "BOX_OUT_OF_IMAGE":
            if iss.line is not None:
                file_line_issues[iss.image][iss.line].append(iss)

    for stem in sorted(file_line_issues.keys()):
        if stem in removed_images:
            continue
        lbl_path = ds.label_path(stem)
        if not lbl_path.exists():
            continue

        raw_lines = lbl_path.read_text(encoding="utf-8", errors="replace").splitlines()
        line_actions: dict[int, tuple[str, str, str]] = {}

        for line_num, iss_list in file_line_issues[stem].items():
            if line_num < 1 or line_num > len(raw_lines):
                continue
            orig_text = raw_lines[line_num - 1]

            has_drop = any(i.code in DROP_LINE_CODES for i in iss_list)
            if has_drop:
                line_actions[line_num] = ("drop_line", orig_text, "")
            else:
                # BOX_OUT_OF_IMAGE
                try:
                    cls, cx, cy, w, h = parse_yolo_line(orig_text)
                    x1 = cx - w / 2.0
                    y1 = cy - h / 2.0
                    x2 = cx + w / 2.0
                    y2 = cy + h / 2.0
                    x1_c = max(0.0, min(1.0, x1))
                    y1_c = max(0.0, min(1.0, y1))
                    x2_c = max(0.0, min(1.0, x2))
                    y2_c = max(0.0, min(1.0, y2))
                    new_w = x2_c - x1_c
                    new_h = y2_c - y1_c
                    if new_w <= 0.0 or new_h <= 0.0:
                        line_actions[line_num] = ("drop_line", orig_text, "")
                    else:
                        new_cx = (x1_c + x2_c) / 2.0
                        new_cy = (y1_c + y2_c) / 2.0
                        clipped_str = f"{cls} {new_cx:.6f} {new_cy:.6f} {new_w:.6f} {new_h:.6f}"
                        line_actions[line_num] = ("clip_box", orig_text, clipped_str)
                except Exception:
                    line_actions[line_num] = ("drop_line", orig_text, "")

        new_lines: list[str] = []
        for idx, text in enumerate(raw_lines):
            ln = idx + 1
            if ln in line_actions:
                action, before, after = line_actions[ln]
                fixes.append({
                    "image": stem,
                    "line": ln,
                    "action": action,
                    "before": before,
                    "after": after,
                })
                if action == "clip_box":
                    new_lines.append(after)
                # action == "drop_line": bỏ qua không thêm vào new_lines
            else:
                new_lines.append(text)

        new_content = "\n".join(new_lines)
        if new_content and not new_content.endswith("\n"):
            new_content += "\n"
        lbl_path.write_text(new_content, encoding="utf-8")

    return fixes
