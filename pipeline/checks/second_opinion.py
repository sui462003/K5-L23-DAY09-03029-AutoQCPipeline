"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line
from ..model_cache import get_preds


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    so_cfg = cfg.get("second_opinion", {})
    conf_thresh = so_cfg.get("conf", 0.25)
    min_area_px = so_cfg.get("min_area_px", 600)
    fp_conf = so_cfg.get("fp_conf", 0.1)
    iou_missing = so_cfg.get("iou_missing", 0.3)
    iou_match = so_cfg.get("iou_match", 0.5)
    iou_loose = so_cfg.get("iou_loose", 0.5)

    issues: list[Issue] = []

    for img_p in ds.image_files():
        stem = img_p.stem
        if stem not in preds:
            continue
        if not ds.label_path(stem).exists():
            continue

        im_size = ds.image_size(stem)
        if im_size is None:
            continue
        img_w, img_h = im_size

        all_preds = preds.get(stem) or []
        valid_boxes = ds.valid_boxes(stem)

        # Lọc tập dự đoán P: conf >= conf_thresh VÀ diện tích px >= min_area_px
        p_filtered = []
        for r in all_preds:
            if len(r) >= 6:
                pred_cls, pred_conf, cx, cy, w, h = r[0], r[1], r[2], r[3], r[4], r[5]
                area_px = (w * img_w) * (h * img_h)
                if pred_conf >= conf_thresh and area_px >= min_area_px:
                    p_filtered.append(r)

        # 1. Duyệt từng dự đoán trong P theo thứ tự
        for r in p_filtered:
            pred_cls, pred_conf, cx, cy, w, h = r[0], r[1], r[2], r[3], r[4], r[5]
            r_box = (cx, cy, w, h)

            cands_same = []
            cands_diff = []

            for lbl_cls, l_cx, l_cy, l_w, l_h in valid_boxes:
                lbl_box = (l_cx, l_cy, l_w, l_h)
                iou = iou_xywh(r_box, lbl_box)
                if iou >= iou_missing:
                    if lbl_cls == pred_cls:
                        cands_same.append(iou)
                    else:
                        cands_diff.append(iou)

            # Quyết định theo thứ tự:
            # (1) cands rỗng -> POSSIBLE_MISSING
            if not cands_same and not cands_diff:
                cls_name = ds.classes[pred_cls] if 0 <= pred_cls < len(ds.classes) else str(pred_cls)
                issues.append(Issue(
                    check="second_opinion",
                    severity=WARN,
                    code="POSSIBLE_MISSING",
                    image=stem,
                    line=None,
                    message=f"model thấy {cls_name} (conf={pred_conf:.2f}), nhãn không có box tương ứng",
                    extra={"conf": pred_conf}
                ))
            # (2) Có cands cùng lớp
            elif cands_same:
                best_same_iou = max(cands_same)
                if best_same_iou < iou_loose:
                    cls_name = ds.classes[pred_cls] if 0 <= pred_cls < len(ds.classes) else str(pred_cls)
                    issues.append(Issue(
                        check="second_opinion",
                        severity=WARN,
                        code="POSSIBLE_LOOSE_BOX",
                        image=stem,
                        line=None,
                        message=f"box nhãn cùng lớp {cls_name} nhưng lệch/lỏng (IoU={best_same_iou:.2f} < {iou_loose})",
                        extra={"conf": pred_conf, "iou": round(best_same_iou, 4)}
                    ))
                # Ngược lại: nhãn đúng lớp đã phủ tốt vật này, không cờ
            # (3) Không có cands cùng lớp, chỉ có cands khác lớp
            else:
                best_diff_iou = max(cands_diff)
                if best_diff_iou >= iou_match:
                    cls_name = ds.classes[pred_cls] if 0 <= pred_cls < len(ds.classes) else str(pred_cls)
                    issues.append(Issue(
                        check="second_opinion",
                        severity=WARN,
                        code="POSSIBLE_WRONG_CLASS",
                        image=stem,
                        line=None,
                        message=f"nghi nhầm lớp: model thấy {cls_name} (conf={pred_conf:.2f}) nhưng nhãn là lớp khác (IoU={best_diff_iou:.2f})",
                        extra={"conf": pred_conf, "iou": round(best_diff_iou, 4)}
                    ))
                # Ngược lại [iou_missing, iou_match): mơ hồ, không cờ gì

        # 2. Kiểm tra POSSIBLE_FALSE_POS theo số dòng
        fp_preds = [
            (p[2], p[3], p[4], p[5])
            for p in all_preds
            if len(p) >= 6 and p[1] >= fp_conf
        ]

        raw_lines = ds.read_label_lines(stem) or []
        for line_num, line_text in raw_lines:
            try:
                lbl_cls, cx, cy, w, h = parse_yolo_line(line_text)
            except ValueError:
                continue
            if not (0 <= lbl_cls < len(ds.classes)):
                continue

            lbl_box = (cx, cy, w, h)
            matched = any(iou_xywh(lbl_box, p_box) >= iou_missing for p_box in fp_preds)
            if not matched:
                issues.append(Issue(
                    check="second_opinion",
                    severity=WARN,
                    code="POSSIBLE_FALSE_POS",
                    image=stem,
                    line=line_num,
                    message=f"box nhãn không khớp với bất kỳ dự đoán nào của model (conf >= {fp_conf})",
                    extra={"class_id": lbl_cls}
                ))

    return issues
