"""
ui/components/treemap_dialog.py
────────────────────────────────────────────────────────────────
미디어 라이브러리 용량 시각화 트리맵 다이얼로그 (TreemapDialog)

기능:
  - 완전한 애플리케이션 모달(Modal) 다이얼로그로 부모 창과의 상호작용 충돌 원천 차단
  - 1100x750px 고해상도 전용 뷰어 (리사이즈 및 전체화면 지원)
  - 5종 핵심 분석 기준 지원:
      1) 📅 연도/월별 (연도 ➔ 월 계층 드릴다운)
      2) 📁 디스크 폴더별 (실제 상대 경로 계층 드릴다운)
      3) 🌍 촬영 지역별 (국가 ➔ 도시 계층 드릴다운)
      4) 📷 촬영 기기별 (제조사 ➔ 모델 계층 드릴다운)
      5) 🎬 미디어 유형별 (사진 vs 동영상)
  - 상단 드릴다운 브레드크럼(Breadcrumb) 내비게이션 바 & [⬆ 상위로] 복귀 버튼
  - 하단 선택 항목 상세 정보 및 [📁 Finder/탐색기에서 열기] 액션
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from src.core.i18n import i18n, t
from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository
from src.ui.components.treemap_widget import (
    TreemapNode, TreemapWidget, format_bytes, format_percentage,
)
from src.ui.theme import Colors, Fonts


class TreemapDialog(QDialog):
    """미디어 용량 시각화 트리맵 전용 모달 다이얼로그"""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        repo: Optional[MediaRepository] = None,
        initial_root: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(t("dialog.treemap.window_title", "🗺 미디어 라이브러리 용량 분석 (Treemap)"))
        self.resize(1100, 750)
        self.setMinimumSize(850, 560)

        self._db = db_manager or DatabaseManager()
        self._repo = repo or MediaRepository(self._db)
        self._initial_root = initial_root

        self._setup_ui()
        self._populate_filters()
        self._load_treemap_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # ── 1. 상단 컨트롤 카드 ──────────────────────────────
        top_card = QFrame()
        top_card.setObjectName("Card")
        top_card.setStyleSheet("""
            QFrame#Card {
                background-color: #FFFFFF;
                border: 1px solid #E5E8EB;
                border-radius: 12px;
                padding: 4px;
            }
        """)
        top_layout = QVBoxLayout(top_card)
        top_layout.setContentsMargins(14, 10, 14, 10)
        top_layout.setSpacing(10)

        # 1단: 필터 옵션 행
        filter_row = QHBoxLayout()
        filter_row.setSpacing(14)

        _lbl_style = "font-size: 11px; font-weight: bold; color: #495057; border: none; background: transparent;"

        # 저장 위치 콤보
        col_root = QVBoxLayout()
        col_root.setSpacing(3)
        lbl_root = QLabel("📂 저장 위치")
        lbl_root.setStyleSheet(_lbl_style)
        self._root_combo = QComboBox()
        self._root_combo.setFixedHeight(28)
        self._root_combo.currentIndexChanged.connect(self._on_filter_changed)
        col_root.addWidget(lbl_root)
        col_root.addWidget(self._root_combo)
        filter_row.addLayout(col_root, stretch=3)

        # 분석 기준 콤보
        col_mode = QVBoxLayout()
        col_mode.setSpacing(3)
        lbl_mode = QLabel("📑 분석 기준")
        lbl_mode.setStyleSheet(_lbl_style)
        self._mode_combo = QComboBox()
        self._mode_combo.setFixedHeight(28)
        self._mode_combo.addItem("📅 연도/월별 (시계열 계층)", "date")
        self._mode_combo.addItem("📁 디스크 폴더별 (실제 상대경로)", "folder")
        self._mode_combo.addItem("🌍 촬영 지역별 (국가 ➔ 주/도 ➔ 도시)", "location")
        self._mode_combo.addItem("📷 촬영 기기별 (제조사/모델)", "camera")
        self._mode_combo.addItem("🎬 미디어 유형별 (사진 vs 동영상)", "type")
        self._mode_combo.currentIndexChanged.connect(self._on_filter_changed)
        col_mode.addWidget(lbl_mode)
        col_mode.addWidget(self._mode_combo)
        filter_row.addLayout(col_mode, stretch=2)

        # 미디어 유형 필터 콤보
        col_type = QVBoxLayout()
        col_type.setSpacing(3)
        lbl_type = QLabel("🎬 미디어 유형")
        lbl_type.setStyleSheet(_lbl_style)
        self._type_combo = QComboBox()
        self._type_combo.setFixedHeight(28)
        self._type_combo.addItem("전체 미디어", "")
        self._type_combo.addItem("📷 사진만", "photo")
        self._type_combo.addItem("🎬 동영상만", "video")
        self._type_combo.currentIndexChanged.connect(self._on_filter_changed)
        col_type.addWidget(lbl_type)
        col_type.addWidget(self._type_combo)
        filter_row.addLayout(col_type, stretch=1)

        top_layout.addLayout(filter_row)

        # 구분선
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #F1F3F6; max-height: 1px; border: none;")
        top_layout.addWidget(sep)

        # 2단: 브레드크럼(Breadcrumb) 경로 바 + 요약 텍스트
        nav_row = QHBoxLayout()
        nav_row.setSpacing(10)

        self._up_btn = QPushButton("⬆ 상위로")
        self._up_btn.setObjectName("SecondaryButton")
        self._up_btn.setCursor(Qt.PointingHandCursor)
        self._up_btn.setFixedHeight(26)
        self._up_btn.setStyleSheet("""
            QPushButton#SecondaryButton {
                font-size: 11px;
                font-weight: 600;
                padding: 2px 10px;
                border: 1px solid #CED4DA;
                border-radius: 6px;
                background-color: #F8F9FA;
            }
            QPushButton#SecondaryButton:hover {
                background-color: #E9ECEF;
            }
            QPushButton#SecondaryButton:disabled {
                color: #ADB5BD;
                border-color: #E9ECEF;
                background-color: #F8F9FA;
            }
        """)
        self._up_btn.setEnabled(False)
        self._up_btn.clicked.connect(self._go_up)
        nav_row.addWidget(self._up_btn)

        self._breadcrumb_label = QLabel("📍 현재 위치: 🏠 전체")
        self._breadcrumb_label.setStyleSheet("font-size: 12px; font-weight: 700; color: #212529;")
        nav_row.addWidget(self._breadcrumb_label)

        nav_row.addStretch()

        self._summary_label = QLabel("불러오는 중...")
        self._summary_label.setStyleSheet("font-size: 11px; color: #495057; font-weight: 500;")
        nav_row.addWidget(self._summary_label)

        top_layout.addLayout(nav_row)
        layout.addWidget(top_card)

        # ── 2. 중앙 트리맵 위젯 ──────────────────────────────
        self._treemap = TreemapWidget()
        self._treemap.setStyleSheet("""
            TreemapWidget {
                border: 1px solid #E5E8EB;
                border-radius: 12px;
                background-color: #FFFFFF;
            }
        """)
        self._treemap.node_selected.connect(self._on_node_selected)
        self._treemap.drilldown_changed.connect(self._on_drilldown_changed)
        self._treemap.node_double_clicked.connect(self._on_node_double_clicked)
        layout.addWidget(self._treemap, stretch=1)

        # ── 3. 하단 액션 바 ──────────────────────────────────
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)

        self._selection_label = QLabel("타일을 클릭하면 상세 정보가 표시됩니다.")
        self._selection_label.setStyleSheet("font-size: 11px; color: #495057; font-weight: 500;")
        bottom_bar.addWidget(self._selection_label)
        bottom_bar.addStretch()

        self._open_btn = QPushButton("📁 Finder/탐색기에서 열기")
        self._open_btn.setObjectName("SecondaryButton")
        self._open_btn.setCursor(Qt.PointingHandCursor)
        self._open_btn.setFixedHeight(30)
        self._open_btn.setEnabled(False)
        self._open_btn.setStyleSheet("""
            QPushButton#SecondaryButton {
                font-size: 11px;
                padding: 2px 14px;
                border: 1px solid #0072DE;
                color: #0072DE;
                border-radius: 6px;
                background: transparent;
            }
            QPushButton#SecondaryButton:hover {
                background-color: #E8F3FF;
            }
            QPushButton#SecondaryButton:disabled {
                border-color: #CED4DA;
                color: #ADB5BD;
            }
        """)
        self._open_btn.clicked.connect(self._open_selected_dir)
        bottom_bar.addWidget(self._open_btn)

        close_btn = QPushButton("닫기 (ESC)")
        close_btn.setObjectName("SecondaryButton")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedHeight(30)
        close_btn.setStyleSheet("""
            QPushButton#SecondaryButton {
                font-size: 11px;
                padding: 2px 16px;
                border: 1px solid #CED4DA;
                border-radius: 6px;
                background-color: #FFFFFF;
                color: #495057;
            }
            QPushButton#SecondaryButton:hover {
                background-color: #F8F9FA;
            }
        """)
        close_btn.clicked.connect(self.accept)
        bottom_bar.addWidget(close_btn)

        layout.addLayout(bottom_bar)

        # ESC 키 단축키 바인딩
        esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc_shortcut.activated.connect(self.accept)

    def _populate_filters(self):
        roots = self._repo.get_output_roots()
        self._root_combo.blockSignals(True)
        self._root_combo.clear()
        self._root_combo.addItem("📂 저장 위치: 전체", "")
        for r in roots:
            short_name = Path(r).name or r
            self._root_combo.addItem(f"📁 {short_name} ({r})", r)

        if self._initial_root:
            idx = self._root_combo.findData(self._initial_root)
            if idx >= 0:
                self._root_combo.setCurrentIndex(idx)

        self._root_combo.blockSignals(False)

    def _on_filter_changed(self):
        self._load_treemap_data()

    def _load_treemap_data(self):
        """선택된 필터 조건에 맞춰 SQLite에서 계층 노드 데이터 생성"""
        root_dir = self._root_combo.currentData()
        mode = self._mode_combo.currentData()
        m_type = self._type_combo.currentData()

        # WHERE 조건절 구성
        where_clauses = ["1=1"]
        params: list = []

        if root_dir:
            where_clauses.append("f.file_path LIKE ?")
            params.append(f"{root_dir}%")

        if m_type:
            where_clauses.append("f.media_type = ?")
            params.append(m_type)

        where_sql = " AND ".join(where_clauses)

        nodes: List[TreemapNode] = []

        if mode == "date":
            # 📅 연도/월별 계층
            sql = f"""
                SELECT 
                    COALESCE(SUBSTR(m.taken_at, 1, 4), '날짜 미상') AS l1,
                    COALESCE(SUBSTR(m.taken_at, 1, 7), '날짜 미상') AS l2,
                    COUNT(*) AS cnt,
                    SUM(f.file_size) AS sz,
                    SUM(CASE WHEN f.media_type='photo' THEN 1 ELSE 0 END) AS p_cnt,
                    SUM(CASE WHEN f.media_type='video' THEN 1 ELSE 0 END) AS v_cnt,
                    MIN(f.file_path) AS sample_path
                FROM media_files f
                LEFT JOIN metadata m ON f.id = m.media_id
                WHERE {where_sql}
                GROUP BY l1, l2
                ORDER BY l1 DESC, l2 DESC
            """
            cur = self._db.conn.execute(sql, params)
            group_map: Dict[str, TreemapNode] = {}
            for row in cur.fetchall():
                l1, l2, cnt, sz, p_cnt, v_cnt, sample_path = row
                sz = sz or 0
                cnt = cnt or 0
                if l1 not in group_map:
                    group_map[l1] = TreemapNode(
                        name=f"{l1}년" if l1.isdigit() else l1,
                        value=0,
                        count=0,
                        path="",
                        meta={"photo_count": 0, "video_count": 0},
                    )
                parent_node = group_map[l1]
                parent_node.value += sz
                parent_node.count += cnt
                parent_node.meta["photo_count"] += (p_cnt or 0)
                parent_node.meta["video_count"] += (v_cnt or 0)

                child_node = TreemapNode(
                    name=l2,
                    value=sz,
                    count=cnt,
                    path="",
                    meta={"photo_count": p_cnt or 0, "video_count": v_cnt or 0},
                )
                parent_node.children.append(child_node)
            nodes = list(group_map.values())

        elif mode == "location":
            # 🌍 촬영 지역별 (국가 ➔ 주/도 ➔ 도시 3단계 계층)
            sql = f"""
                SELECT 
                    COALESCE(NULLIF(m.country_name, ''), '위치정보없음') AS l1,
                    COALESCE(NULLIF(m.state_name, ''), '주/도 미분류') AS l2,
                    COALESCE(NULLIF(m.city_name, ''), '도시 미분류') AS l3,
                    COUNT(*) AS cnt,
                    SUM(f.file_size) AS sz,
                    SUM(CASE WHEN f.media_type='photo' THEN 1 ELSE 0 END) AS p_cnt,
                    SUM(CASE WHEN f.media_type='video' THEN 1 ELSE 0 END) AS v_cnt,
                    MIN(f.file_path) AS sample_path
                FROM media_files f
                LEFT JOIN metadata m ON f.id = m.media_id
                WHERE {where_sql}
                GROUP BY l1, l2, l3
                ORDER BY sz DESC
            """
            cur = self._db.conn.execute(sql, params)
            country_map = {}
            for row in cur.fetchall():
                l1, l2, l3, cnt, sz, p_cnt, v_cnt, sample_path = row
                sz = sz or 0
                cnt = cnt or 0
                p_cnt = p_cnt or 0
                v_cnt = v_cnt or 0

                # 1단계: 국가 노드
                if l1 not in country_map:
                    country_map[l1] = {
                        "node": TreemapNode(
                            name=l1,
                            value=0,
                            count=0,
                            path="",
                            meta={"photo_count": 0, "video_count": 0},
                        ),
                        "states": {},
                    }
                c_entry = country_map[l1]
                c_entry["node"].value += sz
                c_entry["node"].count += cnt
                c_entry["node"].meta["photo_count"] += p_cnt
                c_entry["node"].meta["video_count"] += v_cnt

                # 2단계: 주/도 노드
                state_map = c_entry["states"]
                if l2 not in state_map:
                    state_map[l2] = TreemapNode(
                        name=l2,
                        value=0,
                        count=0,
                        path="",
                        meta={"photo_count": 0, "video_count": 0},
                    )
                s_node = state_map[l2]
                s_node.value += sz
                s_node.count += cnt
                s_node.meta["photo_count"] += p_cnt
                s_node.meta["video_count"] += v_cnt

                # 3단계: 도시 노드
                city_node = TreemapNode(
                    name=l3,
                    value=sz,
                    count=cnt,
                    path="",
                    meta={"photo_count": p_cnt, "video_count": v_cnt},
                )
                s_node.children.append(city_node)

            # 국가 노드에 주/도 노드들 연결
            for c_entry in country_map.values():
                c_node = c_entry["node"]
                c_node.children = list(c_entry["states"].values())

            nodes = [entry["node"] for entry in country_map.values()]

        elif mode == "camera":
            # 📷 촬영 기기별 (제조사 ➔ 모델)
            sql = f"""
                SELECT 
                    COALESCE(NULLIF(m.camera_make, ''), '기기 정보 없음') AS l1,
                    COALESCE(NULLIF(m.camera_model, ''), '기타 모델') AS l2,
                    COUNT(*) AS cnt,
                    SUM(f.file_size) AS sz,
                    SUM(CASE WHEN f.media_type='photo' THEN 1 ELSE 0 END) AS p_cnt,
                    SUM(CASE WHEN f.media_type='video' THEN 1 ELSE 0 END) AS v_cnt,
                    MIN(f.file_path) AS sample_path
                FROM media_files f
                LEFT JOIN metadata m ON f.id = m.media_id
                WHERE {where_sql}
                GROUP BY l1, l2
                ORDER BY sz DESC
            """
            cur = self._db.conn.execute(sql, params)
            group_map = {}
            for row in cur.fetchall():
                l1, l2, cnt, sz, p_cnt, v_cnt, sample_path = row
                sz = sz or 0
                cnt = cnt or 0
                if l1 not in group_map:
                    group_map[l1] = TreemapNode(
                        name=l1,
                        value=0,
                        count=0,
                        path="",
                        meta={"photo_count": 0, "video_count": 0},
                    )
                parent_node = group_map[l1]
                parent_node.value += sz
                parent_node.count += cnt
                parent_node.meta["photo_count"] += (p_cnt or 0)
                parent_node.meta["video_count"] += (v_cnt or 0)

                child_node = TreemapNode(
                    name=l2,
                    value=sz,
                    count=cnt,
                    path="",
                    meta={"photo_count": p_cnt or 0, "video_count": v_cnt or 0},
                )
                parent_node.children.append(child_node)
            nodes = list(group_map.values())

        elif mode == "folder":
            # 📁 디스크 실제 디렉토리 구조 기반 계층 트리 빌드
            sql = f"""
                SELECT f.file_path, f.file_size, f.media_type
                FROM media_files f
                WHERE {where_sql}
            """
            cur = self._db.conn.execute(sql, params)
            rows = cur.fetchall()

            # base_dir 결정: 유효한 root_dir가 있으면 사용, 없으면 전체 파일들의 commonpath 자동 산출
            base_dir = Path(root_dir) if (root_dir and os.path.exists(root_dir)) else None
            if not base_dir and rows:
                valid_paths = [r[0] for r in rows if r[0] and os.path.isabs(r[0])]
                if valid_paths:
                    try:
                        common = os.path.commonpath(valid_paths)
                        if common and common != os.path.abspath(os.sep):
                            base_dir = Path(common)
                    except Exception:
                        base_dir = None

            # 폴더 계층 트리 빌드: { segment: { "node": TreemapNode, "sub": {} } }
            tree_root = {}

            def get_or_create_node(parent_dict, seg_parts, current_rel_path, f_sz, f_mtype):
                seg = seg_parts[0]
                cur_path = current_rel_path / seg
                abs_path_str = str(base_dir / cur_path) if base_dir else ""

                if seg not in parent_dict:
                    parent_dict[seg] = {
                        "node": TreemapNode(
                            name=seg,
                            value=0,
                            count=0,
                            path=abs_path_str if (abs_path_str and os.path.exists(abs_path_str)) else "",
                            meta={"photo_count": 0, "video_count": 0},
                        ),
                        "sub": {},
                    }
                entry = parent_dict[seg]
                entry["node"].value += f_sz
                entry["node"].count += 1
                if f_mtype == "photo":
                    entry["node"].meta["photo_count"] += 1
                else:
                    entry["node"].meta["video_count"] += 1

                if len(seg_parts) > 1:
                    get_or_create_node(entry["sub"], seg_parts[1:], cur_path, f_sz, f_mtype)

            for row in rows:
                f_path, sz, mtype = row
                sz = sz or 0
                p = Path(f_path)
                try:
                    if base_dir:
                        rel = p.parent.relative_to(base_dir)
                    else:
                        rel = Path(p.parent.name)
                    parts = rel.parts
                except Exception:
                    parts = (p.parent.name,)

                if not parts or parts == ('.',):
                    parts = (base_dir.name if base_dir else "기본 폴더",)

                get_or_create_node(tree_root, parts, Path(""), sz, mtype)

            def build_node_list(d):
                res = []
                for entry in d.values():
                    node = entry["node"]
                    if entry["sub"]:
                        node.children = build_node_list(entry["sub"])
                    res.append(node)
                return sorted(res, key=lambda n: n.value, reverse=True)

            nodes = build_node_list(tree_root)

        elif mode == "type":
            # 🎬 미디어 유형별
            sql = f"""
                SELECT 
                    CASE WHEN f.media_type='photo' THEN '📷 사진' ELSE '🎬 동영상' END AS l1,
                    COALESCE(SUBSTR(m.taken_at, 1, 4), '날짜 미상') AS l2,
                    COUNT(*) AS cnt,
                    SUM(f.file_size) AS sz,
                    MIN(f.file_path) AS sample_path
                FROM media_files f
                LEFT JOIN metadata m ON f.id = m.media_id
                WHERE {where_sql}
                GROUP BY l1, l2
                ORDER BY sz DESC
            """
            cur = self._db.conn.execute(sql, params)
            group_map = {}
            for row in cur.fetchall():
                l1, l2, cnt, sz, sample_path = row
                sz = sz or 0
                cnt = cnt or 0
                if l1 not in group_map:
                    group_map[l1] = TreemapNode(
                        name=l1,
                        value=0,
                        count=0,
                        path="",
                    )
                parent_node = group_map[l1]
                parent_node.value += sz
                parent_node.count += cnt

                child_node = TreemapNode(
                    name=f"{l2}년" if l2.isdigit() else l2,
                    value=sz,
                    count=cnt,
                    path="",
                )
                parent_node.children.append(child_node)
            nodes = list(group_map.values())

        # 전체 통계 계산
        tot_cnt = sum(n.count for n in nodes)
        tot_sz = sum(n.value for n in nodes)
        self._summary_label.setText(
            f"총 {tot_cnt:,}개 파일  |  {format_bytes(tot_sz)}  |  총 {len(nodes)}개 그룹"
        )

        self._treemap.set_data(nodes)
        self._selection_label.setText("타일을 클릭하면 상세 정보가 표시됩니다.")
        self._open_btn.setEnabled(False)

    def _go_up(self):
        self._treemap.go_up()

    def _on_drilldown_changed(self, breadcrumb: List[TreemapNode]):
        self._up_btn.setEnabled(bool(breadcrumb))
        if not breadcrumb:
            self._breadcrumb_label.setText("📍 현재 위치: 🏠 전체")
        else:
            names = [b.name for b in breadcrumb]
            self._breadcrumb_label.setText(f"📍 현재 위치: 🏠 전체  ➔  {'  ➔  '.join(names)}")

    def _on_node_selected(self, node: Optional[TreemapNode]):
        if not node:
            self._selection_label.setText("타일을 클릭하면 상세 정보가 표시됩니다.")
            self._open_btn.setEnabled(False)
            return

        detail_parts = [
            f"선택: 📂 {node.name}",
            f"용량: {format_bytes(node.value)} ({format_percentage(node.percentage)})",
            f"파일: {node.count:,}개",
        ]
        p_cnt = node.meta.get("photo_count")
        v_cnt = node.meta.get("video_count")
        if p_cnt is not None and v_cnt is not None:
            detail_parts.append(f"(사진 {p_cnt:,}, 동영상 {v_cnt:,})")

        self._selection_label.setText("   |   ".join(detail_parts))
        self._open_btn.setEnabled(bool(node.path and os.path.exists(node.path)))

    def _on_node_double_clicked(self, node: TreemapNode):
        """더블 클릭 시 동작 (더블클릭은 순수 드릴다운 전용으로 통일, 리프 노드에서는 No-op)"""
        pass

    def _open_selected_dir(self):
        node = self._treemap.get_selected_node()
        if node and node.path and os.path.exists(node.path):
            self._open_dir(node.path)
        else:
            QMessageBox.information(self, "알림", "선택된 폴더의 디스크 경로를 찾을 수 없습니다.")

    def _open_dir(self, dir_path: str):
        if sys.platform == "darwin":
            subprocess.run(["open", dir_path])
        elif sys.platform == "win32":
            subprocess.run(["explorer", dir_path])
