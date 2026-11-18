"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line


def run(ds, cfg):
    issues: list[Issue] = []
    lf_cfg = cfg.get("label_format", {})
    overflow_tol = lf_cfg.get("overflow_tol", 0.002)
    min_box_px = lf_cfg.get("min_box_px", 12)
    max_box_frac = lf_cfg.get("max_box_frac", 0.95)
    dup_box_iou = lf_cfg.get("dup_box_iou", 0.9)
    n_classes = len(ds.classes)

    for p in ds.label_files():
        stem = p.stem
        raw_lines = ds.read_label_lines(stem)
        if not raw_lines:
            continue

        im_size = ds.image_size(stem)
        seen_boxes: list[tuple[int, tuple[float, float, float, float], int]] = []

        for line_num, text in raw_lines:
            # 1. BAD_FORMAT
            try:
                cls, cx, cy, w, h = parse_yolo_line(text)
            except ValueError:
                issues.append(Issue(
                    check="label_format",
                    severity=ERROR,
                    code="BAD_FORMAT",
                    image=stem,
                    line=line_num,
                    message=f"dòng không đúng 5 cột số: '{text}'"
                ))
                continue

            # 2. BAD_CLASS_ID
            if not (0 <= cls < n_classes):
                issues.append(Issue(
                    check="label_format",
                    severity=ERROR,
                    code="BAD_CLASS_ID",
                    image=stem,
                    line=line_num,
                    message=f"ID lớp {cls} ngoài dải 0..{n_classes - 1}",
                    extra={"class_id": cls}
                ))
                continue

            # 3. BOX_ZERO
            if w <= 0 or h <= 0:
                issues.append(Issue(
                    check="label_format",
                    severity=ERROR,
                    code="BOX_ZERO",
                    image=stem,
                    line=line_num,
                    message=f"box có kích thước <= 0: w={w}, h={h}",
                    extra={"w": w, "h": h}
                ))
                continue

            # 4. BOX_OUT_OF_IMAGE
            x1 = cx - w / 2.0
            y1 = cy - h / 2.0
            x2 = cx + w / 2.0
            y2 = cy + h / 2.0
            overflow = max(0.0, -x1, -y1, x2 - 1.0, y2 - 1.0)
            if overflow > overflow_tol:
                issues.append(Issue(
                    check="label_format",
                    severity=ERROR,
                    code="BOX_OUT_OF_IMAGE",
                    image=stem,
                    line=line_num,
                    message=f"box tràn ngoài ảnh mức {overflow:.4f} > tol {overflow_tol}",
                    extra={"overflow": overflow}
                ))

            # 5. DUP_BOX
            for prev_cls, prev_box, prev_line in seen_boxes:
                if prev_cls == cls and iou_xywh((cx, cy, w, h), prev_box) > dup_box_iou:
                    issues.append(Issue(
                        check="label_format",
                        severity=ERROR,
                        code="DUP_BOX",
                        image=stem,
                        line=line_num,
                        message=f"box trùng lặp với dòng {prev_line} (cùng lớp {cls}, IoU > {dup_box_iou})"
                    ))
                    break
            seen_boxes.append((cls, (cx, cy, w, h), line_num))

            # 6. BOX_TINY
            if im_size is not None:
                img_w, img_h = im_size
                box_w_px = w * img_w
                box_h_px = h * img_h
                short_side_px = min(box_w_px, box_h_px)
                if short_side_px < min_box_px:
                    issues.append(Issue(
                        check="label_format",
                        severity=WARN,
                        code="BOX_TINY",
                        image=stem,
                        line=line_num,
                        message=f"cạnh ngắn của box ({short_side_px:.1f}px) < {min_box_px}px",
                        extra={"short_side_px": short_side_px}
                    ))

            # 7. BOX_HUGE
            if w * h > max_box_frac:
                issues.append(Issue(
                    check="label_format",
                    severity=WARN,
                    code="BOX_HUGE",
                    image=stem,
                    line=line_num,
                    message=f"box quá lớn: diện tích {w * h:.3f} > {max_box_frac}",
                    extra={"area_frac": w * h}
                ))

    return issues
