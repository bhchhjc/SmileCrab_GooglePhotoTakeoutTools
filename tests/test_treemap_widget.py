"""
tests/test_treemap_widget.py
────────────────────────────────────────────────────────────────
Squarified Treemap 알고리즘 및 위젯/다이얼로그 단위 테스트
"""

import os
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

from src.data.database import DatabaseManager
from src.data.repositories.media_repo import MediaRepository
from src.ui.components.treemap_widget import (
    TreemapNode, TreemapWidget, format_bytes, squarify,
)
from src.ui.components.treemap_dialog import TreemapDialog


app = QApplication.instance() or QApplication([])


class TestTreemapWidget(unittest.TestCase):
    def setUp(self):
        self.nodes = [
            TreemapNode(name="2023", value=5000000, count=500),
            TreemapNode(name="2022", value=3000000, count=300),
            TreemapNode(name="2021", value=2000000, count=200),
        ]

    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 * 1024 * 5), "5.0 MB")
        self.assertEqual(format_bytes(1024 * 1024 * 1024 * 2), "2.0 GB")

    def test_squarify_algorithm(self):
        w, h = 800.0, 600.0
        squarify(self.nodes, 0, 0, w, h)

        total_percentage = sum(n.percentage for n in self.nodes)
        self.assertAlmostEqual(total_percentage, 100.0, places=1)

        for n in self.nodes:
            self.assertGreater(n.rect.width(), 0)
            self.assertGreater(n.rect.height(), 0)
            self.assertLessEqual(n.rect.right(), w + 0.01)
            self.assertLessEqual(n.rect.bottom(), h + 0.01)

    def test_squarify_empty(self):
        empty_nodes = []
        squarify(empty_nodes, 0, 0, 800, 600)
        self.assertEqual(len(empty_nodes), 0)

        zero_size_nodes = [TreemapNode(name="Zero", value=0)]
        squarify(zero_size_nodes, 0, 0, 800, 600)
        self.assertEqual(zero_size_nodes[0].rect, QRectF(0, 0, 0, 0))

    def test_widget_drilldown(self):
        child1 = TreemapNode(name="2023/01", value=2500000, count=250)
        child2 = TreemapNode(name="2023/02", value=2500000, count=250)
        self.nodes[0].children = [child1, child2]

        widget = TreemapWidget()
        widget.resize(800, 600)
        widget.set_data(self.nodes)

        self.assertEqual(len(widget._current_nodes), 3)
        self.assertEqual(len(widget.get_breadcrumb()), 0)

        # 드릴다운 실행
        success = widget.drill_down(self.nodes[0])
        self.assertTrue(success)
        self.assertEqual(len(widget._current_nodes), 2)
        self.assertEqual(len(widget.get_breadcrumb()), 1)
        self.assertEqual(widget.get_breadcrumb()[0].name, "2023")

        # 상위 복귀
        up_success = widget.go_up()
        self.assertTrue(up_success)
        self.assertEqual(len(widget._current_nodes), 3)
        self.assertEqual(len(widget.get_breadcrumb()), 0)


class TestTreemapDialog(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test.db"
        self.db = DatabaseManager(self.db_path)
        self.db.initialize()
        self.repo = MediaRepository(self.db)

        # 테스트 미디어 데이터 삽입
        with self.db.conn:
            self.db.conn.execute(
                """
                INSERT INTO media_files (file_path, file_name, file_ext, original_path, file_size, file_hash, media_type, album_name, status)
                VALUES 
                    ('/tmp/output/2023/01/a.jpg', 'a.jpg', '.jpg', '/tmp/orig/a.jpg', 1000000, 'hash1', 'photo', 'album1', 'COMPLETED'),
                    ('/tmp/output/2023/01/b.jpg', 'b.jpg', '.jpg', '/tmp/orig/b.jpg', 2000000, 'hash2', 'photo', 'album1', 'COMPLETED'),
                    ('/tmp/output/2023/02/c.mp4', 'c.mp4', '.mp4', '/tmp/orig/c.mp4', 5000000, 'hash3', 'video', 'album2', 'COMPLETED')
                """
            )
            # 메타데이터
            self.db.conn.execute(
                """
                INSERT INTO metadata (media_id, taken_at, country_name, city_name, camera_make, camera_model)
                VALUES 
                    (1, '2023-01-15 10:00:00', '대한민국', '인천', 'Apple', 'iPhone 13 Pro'),
                    (2, '2023-01-16 11:00:00', '대한민국', '서울', 'Apple', 'iPhone 13 Pro'),
                    (3, '2023-02-20 15:00:00', '일본', '도쿄', 'Sony', 'A7M4')
                """
            )

    def tearDown(self):
        self.db.close()
        self.tmp_dir.cleanup()

    def test_dialog_loading_all_modes(self):
        dialog = TreemapDialog(db_manager=self.db, repo=self.repo)
        
        # 1. Date 모드 (기본)
        self.assertEqual(dialog._mode_combo.currentData(), "date")
        self.assertGreater(len(dialog._treemap._root_nodes), 0)

        # 2. Location 모드
        dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData("location"))
        self.assertEqual(dialog._mode_combo.currentData(), "location")
        self.assertGreater(len(dialog._treemap._root_nodes), 0)

        # 3. Camera 모드
        dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData("camera"))
        self.assertEqual(dialog._mode_combo.currentData(), "camera")
        self.assertGreater(len(dialog._treemap._root_nodes), 0)

        # 4. Folder 모드
        dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData("folder"))
        self.assertEqual(dialog._mode_combo.currentData(), "folder")
        self.assertGreater(len(dialog._treemap._root_nodes), 0)

        # 5. Type 모드
        dialog._mode_combo.setCurrentIndex(dialog._mode_combo.findData("type"))
        self.assertEqual(dialog._mode_combo.currentData(), "type")
        self.assertGreater(len(dialog._treemap._root_nodes), 0)

        dialog.close()


if __name__ == "__main__":
    unittest.main()
