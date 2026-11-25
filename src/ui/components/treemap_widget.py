"""
ui/components/treemap_widget.py
────────────────────────────────────────────────────────────────
Squarified Treemap (타일형 용량 시각화 위젯)

기능:
  - Squarified Treemap 알고리즘을 통한 2D 평면 무손실 직사각형 패킹
  - One UI 감성의 소프트 파스텔 컬러 팔레트 & 고대비 가독성 텍스트 렌더링
  - 마우스 호버(Hover) 시 테두리 하이라이트 및 툴팁
  - 단일 클릭 선택(Select) 및 더블 클릭 드릴다운(Zoom-In / Out)
  - 타일 크기에 맞춤형 반응형(Responsive) 텍스트 (명칭, 용량, 비율, 건수)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QPainter,
    QPainterPath, QPen,
)
from PySide6.QtWidgets import QToolTip, QWidget

from src.ui.theme import Colors, Fonts


PASTEL_PALETTE = [
    # (배경색, 텍스트색, 보조텍스트색, 테두리색)
    (QColor("#E8F2FD"), QColor("#0C58A8"), QColor("#1971C2"), QColor("#A5D8FF")),  # 소프트 블루
    (QColor("#E6FCF5"), QColor("#087F5B"), QColor("#0CA678"), QColor("#96F2D7")),  # 소프트 틸/민트
    (QColor("#F3F0FF"), QColor("#5F3DC4"), QColor("#7950F2"), QColor("#D0BFFF")),  # 소프트 퍼플
    (QColor("#FFF9DB"), QColor("#E67700"), QColor("#F08C00"), QColor("#FFE066")),  # 소프트 옐로우
    (QColor("#FFE8CC"), QColor("#D9480F"), QColor("#E8590C"), QColor("#FFC078")),  # 소프트 오렌지
    (QColor("#FFF0F6"), QColor("#A61E4D"), QColor("#C2255C"), QColor("#FCC2D7")),  # 소프트 핑크
    (QColor("#EBFBEE"), QColor("#2B8A3E"), QColor("#37B24D"), QColor("#B2F2BB")),  # 소프트 그린
    (QColor("#F8F9FA"), QColor("#343A40"), QColor("#495057"), QColor("#CED4DA")),  # 소프트 그레이
    (QColor("#E3FAFC"), QColor("#0B7285"), QColor("#1098AD"), QColor("#99E9F2")),  # 소프트 시안
    (QColor("#F1F3F5"), QColor("#212529"), QColor("#495057"), QColor("#DEE2E6")),  # 뉴트럴 그레이
]


def format_bytes(size: int) -> str:
    """바이트 단위 문자열 변환"""
    if size < 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} PB"


def format_percentage(pct: float) -> str:
    """비율 문자열 포맷팅 (0.1% 미만의 극소수 비율도 정밀 표시)"""
    if pct < 0.01 and pct > 0:
        return "< 0.01%"
    elif pct < 0.1:
        return f"{pct:.2f}%"
    return f"{pct:.1f}%"


@dataclass
class TreemapNode:
    """트리맵 단일 타일 메타데이터"""
    name: str
    value: int                    # 용량 (bytes)
    count: int = 0                # 파일 수
    path: str = ""                # 실제 디렉토리 경로 (선택 시 Finder 열기용)
    meta: Dict[str, Any] = field(default_factory=dict)
    children: List["TreemapNode"] = field(default_factory=list)

    # 렌더링 런타임 계산 속성
    rect: QRectF = field(default_factory=QRectF)
    color_idx: int = 0
    percentage: float = 0.0


def squarify(nodes: List[TreemapNode], x: float, y: float, w: float, h: float) -> None:
    """
    Bruls-Huizing-van Wijk 표준 Squarified Treemap 알고리즘 + 최소 가시 면적 보정(Clamping).
    주어진 (x, y, w, h) 평면에 노드들의 value 크기 비율에 맞춰 종횡비를 1에 가깝게 직사각형 배치합니다.
    극소수(0.01% 등) 항목도 소멸되지 않고 최소한의 가시성을 확보할 수 있도록 시각적 가중치를 보정합니다.
    """
    valid_nodes = [n for n in nodes if n.value > 0]
    for n in nodes:
        n.rect = QRectF(0, 0, 0, 0)

    if not valid_nodes or w <= 0 or h <= 0:
        return

    total_val = sum(n.value for n in valid_nodes)
    if total_val <= 0:
        return

    # 1. 전체 대비 실제 정밀 비율 계산 (타일 내부 텍스트 및 툴팁 표기용: 100% 무왜곡)
    for n in valid_nodes:
        n.percentage = (n.value / total_val) * 100.0

    # 2. 극소수 타일 소멸 방지를 위한 최소 가시 면적 보정 (Minimum Area Clamping)
    # 노드 개수에 맞춰 적응형 최소 비율 산출 (노드당 최소 0.6% ~ 최대 2.5% 보장)
    min_ratio = min(0.025, max(0.006, 0.25 / len(valid_nodes)))
    min_scaled_val = total_val * min_ratio

    visual_weights = [max(n.value, min_scaled_val) for n in valid_nodes]
    total_weight = sum(visual_weights)

    total_area = w * h
    scaled_nodes = [
        (n, (visual_weights[i] / total_weight) * total_area)
        for i, n in enumerate(valid_nodes)
    ]

    def layout_row(row: List[Tuple[TreemapNode, float]], rx: float, ry: float, rw: float, rh: float):
        row_area = sum(s for _, s in row)
        if rw < rh:
            # 가로 폭이 더 짧을 때: 상단부터 가로 방향으로 배치
            row_h = row_area / rw if rw > 0 else 0
            cx = rx
            for node, s in row:
                item_w = s / row_h if row_h > 0 else 0
                node.rect = QRectF(cx, ry, item_w, row_h)
                cx += item_w
            return rx, ry + row_h, rw, max(0.0, rh - row_h)
        else:
            # 세로 높이가 더 짧을 때: 좌측부터 세로 방향으로 배치
            row_w = row_area / rh if rh > 0 else 0
            cy = ry
            for node, s in row:
                item_h = s / row_w if row_w > 0 else 0
                node.rect = QRectF(rx, cy, row_w, item_h)
                cy += item_h
            return rx + row_w, ry, max(0.0, rw - row_w), rh

    def worst_ratio(row: List[Tuple[TreemapNode, float]], side: float) -> float:
        if not row or side <= 0:
            return float("inf")
        row_area = sum(s for _, s in row)
        if row_area <= 0:
            return float("inf")
        side2 = side * side
        max_s = max(s for _, s in row)
        min_s = min(s for _, s in row)
        return max((side2 * max_s) / (row_area * row_area), (row_area * row_area) / (side2 * min_s))

    cur_x, cur_y, cur_w, cur_h = x, y, w, h
    current_row: List[Tuple[TreemapNode, float]] = []

    for item in scaled_nodes:
        side = min(cur_w, cur_h)
        if not current_row:
            current_row.append(item)
        else:
            cur_worst = worst_ratio(current_row, side)
            new_worst = worst_ratio(current_row + [item], side)
            if new_worst <= cur_worst:
                current_row.append(item)
            else:
                cur_x, cur_y, cur_w, cur_h = layout_row(current_row, cur_x, cur_y, cur_w, cur_h)
                side = min(cur_w, cur_h)
                current_row = [item]

    if current_row:
        layout_row(current_row, cur_x, cur_y, cur_w, cur_h)


class TreemapWidget(QWidget):
    """
    초고속 QPainter 기반 인터랙티브 트리맵 위젯
    """

    node_selected = Signal(object)       # TreemapNode 클릭 시 방출
    node_double_clicked = Signal(object) # TreemapNode 더블클릭 시 방출
    drilldown_changed = Signal(list)     # 드릴다운 경로 변경 시 [TreemapNode, ...] 방출

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

        self._root_nodes: List[TreemapNode] = []
        self._current_nodes: List[TreemapNode] = []
        self._breadcrumb: List[TreemapNode] = []  # 드릴다운 히스토리 스택

        self._hovered_node: Optional[TreemapNode] = None
        self._selected_node: Optional[TreemapNode] = None

        self.setMinimumSize(400, 300)

    def set_data(self, nodes: List[TreemapNode]):
        """루트 데이터 설정 및 초기화"""
        self._root_nodes = sorted(nodes, key=lambda n: n.value, reverse=True)
        # 색상 인덱스 부여
        for idx, n in enumerate(self._root_nodes):
            n.color_idx = idx % len(PASTEL_PALETTE)
            self._assign_colors_recursive(n, n.color_idx)

        self._breadcrumb = []
        self._current_nodes = self._root_nodes
        self._hovered_node = None
        self._selected_node = None
        self._recalculate_layout()
        self.update()
        self.drilldown_changed.emit(self._breadcrumb)

    def _assign_colors_recursive(self, parent: TreemapNode, base_idx: int):
        for idx, child in enumerate(parent.children):
            child.color_idx = (base_idx + idx) % len(PASTEL_PALETTE)
            self._assign_colors_recursive(child, child.color_idx)

    def drill_down(self, node: TreemapNode) -> bool:
        """하위 노드로 드릴다운 (Zoom-In)"""
        if not node.children:
            return False
        self._breadcrumb.append(node)
        self._current_nodes = sorted(node.children, key=lambda n: n.value, reverse=True)
        self._hovered_node = None
        self._selected_node = None
        self._recalculate_layout()
        self.update()
        self.drilldown_changed.emit(self._breadcrumb)
        return True

    def go_up(self) -> bool:
        """상위 노드로 복귀 (Zoom-Out)"""
        if not self._breadcrumb:
            return False
        self._breadcrumb.pop()
        if not self._breadcrumb:
            self._current_nodes = self._root_nodes
        else:
            self._current_nodes = sorted(self._breadcrumb[-1].children, key=lambda n: n.value, reverse=True)
        self._hovered_node = None
        self._selected_node = None
        self._recalculate_layout()
        self.update()
        self.drilldown_changed.emit(self._breadcrumb)
        return True

    def get_breadcrumb(self) -> List[TreemapNode]:
        return list(self._breadcrumb)

    def get_selected_node(self) -> Optional[TreemapNode]:
        return self._selected_node

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalculate_layout()

    def _recalculate_layout(self):
        w = max(10, self.width() - 8)
        h = max(10, self.height() - 8)
        squarify(self._current_nodes, 4, 4, w, h)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        # 배경 클리어
        painter.fillRect(self.rect(), QColor("#FFFFFF"))

        if not self._current_nodes:
            painter.setPen(QColor(Colors.TEXT_SECONDARY))
            painter.setFont(QFont(".AppleSystemUIFont", 13))
            painter.drawText(self.rect(), Qt.AlignCenter, "표시할 미디어 용량 데이터가 없습니다.")
            return

        font_title = QFont(".AppleSystemUIFont", 11)
        font_title.setBold(True)
        font_sub = QFont(".AppleSystemUIFont", 10)
        font_detail = QFont(".AppleSystemUIFont", 9)

        fm_title = QFontMetrics(font_title)
        fm_sub = QFontMetrics(font_sub)

        for node in self._current_nodes:
            r = node.rect
            if r.width() < 1 or r.height() < 1:
                continue

            # 타일 간격 1px 패딩 적용
            tile_rect = r.adjusted(1, 1, -1, -1)
            if tile_rect.width() <= 2 or tile_rect.height() <= 2:
                continue

            # 색상 추출
            bg_col, txt_col, sub_col, border_col = PASTEL_PALETTE[node.color_idx]

            is_hovered = (node == self._hovered_node)
            is_selected = (node == self._selected_node)

            # 배경 채우기
            if is_hovered:
                # 호버 시 조금 더 밝고 선명하게
                painter.setBrush(QBrush(bg_col.lighter(105)))
            else:
                painter.setBrush(QBrush(bg_col))

            # 테두리 설정
            if is_selected:
                painter.setPen(QPen(QColor(Colors.ACCENT), 2.5))
            elif is_hovered:
                painter.setPen(QPen(QColor(Colors.ACCENT), 1.5))
            else:
                painter.setPen(QPen(border_col, 1))

            # 라운드 사각형 타일 렌더링 (One UI 감성 radius 6px)
            painter.drawRoundedRect(tile_rect, 6, 6)

            # ── 텍스트 렌더링 (타일 크기별 적응형 반응형) ──
            tw = tile_rect.width()
            th = tile_rect.height()

            # 여유 공간이 너무 작으면 텍스트 생략
            if tw < 38 or th < 26:
                continue

            content_rect = tile_rect.adjusted(6, 6, -6, -6)
            cy = content_rect.top()

            # 1줄: 명칭 (폴더명 / 그룹명)
            painter.setFont(font_title)
            painter.setPen(txt_col)
            elided_name = fm_title.elidedText(node.name, Qt.ElideRight, int(content_rect.width()))
            painter.drawText(int(content_rect.left()), int(cy + fm_title.ascent()), elided_name)
            cy += fm_title.height() + 1

            # 2줄: 용량 및 점유율 (%)
            if th >= 52:
                painter.setFont(font_sub)
                painter.setPen(sub_col)
                pct_str = format_percentage(node.percentage)
                size_str = f"{format_bytes(node.value)}  ({pct_str})"
                elided_size = fm_sub.elidedText(size_str, Qt.ElideRight, int(content_rect.width()))
                painter.drawText(int(content_rect.left()), int(cy + fm_sub.ascent()), elided_size)
                cy += fm_sub.height() + 1

            # 3줄: 파일 건수 및 미디어 구성
            if th >= 74 and node.count > 0:
                painter.setFont(font_detail)
                painter.setPen(QColor("#495057"))
                p_cnt = node.meta.get("photo_count")
                v_cnt = node.meta.get("video_count")
                if p_cnt is not None and v_cnt is not None:
                    count_str = f"📸 {node.count:,}개 (사진 {p_cnt:,}, 동영상 {v_cnt:,})"
                else:
                    count_str = f"📸 {node.count:,}개"
                elided_cnt = QFontMetrics(font_detail).elidedText(count_str, Qt.ElideRight, int(content_rect.width()))
                painter.drawText(int(content_rect.left()), int(cy + QFontMetrics(font_detail).ascent()), elided_cnt)

    def mouseMoveEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.pos()
        found = None
        for node in self._current_nodes:
            if node.rect.contains(pos):
                found = node
                break

        if found != self._hovered_node:
            self._hovered_node = found
            if found:
                self.setCursor(Qt.PointingHandCursor)
                # 툴팁 안내
                info_lines = [
                    f"📂 {found.name}",
                    f"💾 용량: {format_bytes(found.value)} ({format_percentage(found.percentage)})",
                    f"📸 파일: {found.count:,}개",
                ]
                if found.children:
                    info_lines.append(f"🔍 더블클릭하여 {len(found.children)}개 하위 항목으로 이동")
                if found.path:
                    info_lines.append(f"📍 경로: {found.path}")
                QToolTip.showText(self.mapToGlobal(pos.toPoint()), "\n".join(info_lines), self)
            else:
                self.unsetCursor()
                QToolTip.hideText()
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position() if hasattr(event, "position") else event.pos()
            for node in self._current_nodes:
                if node.rect.contains(pos):
                    self._selected_node = node
                    self.update()
                    self.node_selected.emit(node)
                    return
            self._selected_node = None
            self.update()
            self.node_selected.emit(None)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position() if hasattr(event, "position") else event.pos()
            for node in self._current_nodes:
                if node.rect.contains(pos):
                    # 자식 노드가 있으면 드릴다운 시도
                    if node.children:
                        self.drill_down(node)
                    else:
                        self.node_double_clicked.emit(node)
                    return
