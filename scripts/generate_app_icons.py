#!/usr/bin/env python3
"""
generate_app_icons.py
'Smile Crab' 컨셉 1 기반 크로스플랫폼(macOS, Windows, Linux) 정밀 앱 아이콘 생성기

- macOS: Apple Human Interface Guidelines 표준 (1024x1024 캔버스, 824x824 스퀘어클, 드롭 섀도우)
- Windows: Windows 11/10 최적화 (외곽 섀도우 제거, 캔버스 꽉 찬 비율, 4배 슈퍼샘플링 안티앨리어싱, 알파 컬러 블리딩 방지)
"""

import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "assets" / "icons"
SOURCE_IMAGE = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT_DIR / "app_icon.png"

# 도둑게 아이콘 배경색 (크림 베이지) - 투명 영역 RGB 블리딩 방지용
BG_COLOR = (250, 235, 196)


def get_cropped_source() -> Image.Image:
    """마스코트 중심 크롭 소스 (680x680)"""
    src = Image.open(SOURCE_IMAGE).convert("RGBA")
    crop_size = 680
    left = (src.width - crop_size) // 2
    top = (src.height - crop_size) // 2
    return src.crop((left, top, left + crop_size, top + crop_size))


def create_squircle_mask(size: int, radius: int) -> Image.Image:
    """고해상도 안티앨리어싱이 적용된 둥근 모서리 마스크 생성"""
    factor = 4
    ss_size = size * factor
    ss_radius = radius * factor
    
    mask = Image.new("L", (ss_size, ss_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, ss_size - 1, ss_size - 1], radius=ss_radius, fill=255)
    
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def generate_macos_icon(cropped_src: Image.Image) -> Image.Image:
    """macOS Big Sur / Sonoma 표준 규격 아이콘 생성"""
    canvas_size = 1024
    inner_size = 824
    radius = 185
    padding = (canvas_size - inner_size) // 2  # 100px
    
    resized_src = cropped_src.resize((inner_size, inner_size), Image.Resampling.LANCZOS)
    
    mask = create_squircle_mask(inner_size, radius)
    rounded_icon = Image.new("RGBA", (inner_size, inner_size), (0, 0, 0, 0))
    rounded_icon.paste(resized_src, (0, 0), mask=mask)
    
    # 섬세한 드롭 섀도우
    shadow_offset = 12
    shadow = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    shadow_mask = create_squircle_mask(inner_size, radius)
    shadow_layer = Image.new("RGBA", (inner_size, inner_size), (0, 0, 0, 45))
    shadow.paste(shadow_layer, (padding, padding + shadow_offset), mask=shadow_mask)
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    
    final_icon = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    final_icon.paste(shadow, (0, 0), mask=shadow)
    final_icon.paste(rounded_icon, (padding, padding), mask=mask)
    
    return final_icon


def clean_alpha_fringe(im: Image.Image, threshold: int = 12) -> Image.Image:
    """Lanczos 다운샘플링 필터의 미세 링잉(Ringing)으로 인한 코너 투명도 노이즈(Alpha < 12) 제거"""
    r, g, b, a = im.split()
    a = a.point(lambda p: 0 if p < threshold else p)
    return Image.merge("RGBA", (r, g, b, a))


def generate_clean_squircle_icon(cropped_src: Image.Image, size: int, radius_ratio: float = 0.1875) -> Image.Image:
    """
    Windows / 공용 클린 엣지 아이콘 생성 (드롭 섀도우 제거, 4배 슈퍼샘플링, 알파 컬러 블리딩 방지)
    - size: 최종 픽셀 크기
    - radius_ratio: 둥근 모서리 곡률 비율 (Windows 11 표준 약 18.75% -> 256px 기준 48px)
    """
    factor = 4
    ss_size = size * factor
    radius = int(ss_size * radius_ratio)
    
    # 4배 고해상도로 리사이즈
    ss_resized = cropped_src.resize((ss_size, ss_size), Image.Resampling.LANCZOS)
    
    # 둥근 모서리 마스크 생성
    mask = Image.new("L", (ss_size, ss_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, ss_size - 1, ss_size - 1], radius=radius, fill=255)
    
    # 컬러 블리딩 방지: 완전 투명 영역(A=0)에도 검은색(0,0,0) 대신 배경색 RGB를 유지
    r, g, b, _ = ss_resized.split()
    ss_clean = Image.merge("RGBA", (r, g, b, mask))
    
    # Lanczos 다운샘플링으로 극강의 모서리 스무딩
    downscaled = ss_clean.resize((size, size), Image.Resampling.LANCZOS)
    return clean_alpha_fringe(downscaled, threshold=12)


def generate_icons():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"🎨 소스 이미지 로드: {SOURCE_IMAGE}")
    
    cropped_src = get_cropped_source()
    
    # 1. macOS 전용 .icns 생성
    mac_icon = generate_macos_icon(cropped_src)
    icns_path = OUTPUT_DIR / "app_icon.icns"
    mac_icon.save(icns_path, format="ICNS")
    print(f"✅ macOS .icns 생성 완료: {icns_path}")
    
    # 2. Windows 전용 멀티사이즈 .ico 생성
    # Windows는 드롭 섀도우 없이 꽉 찬 비율로 각 해상도별 개별 생성
    win_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    win_frames = []
    for w, h in win_sizes:
        frame = generate_clean_squircle_icon(cropped_src, w)
        win_frames.append(frame)
    
    ico_path = OUTPUT_DIR / "app_icon.ico"
    # 가장 큰 256x256을 베이스로, 작은 프레임들을 append하여 멀티사이즈 ICO 구성
    win_frames[-1].save(
        ico_path,
        format="ICO",
        sizes=win_sizes,
        append_images=win_frames[:-1]
    )
    print(f"✅ Windows .ico 정밀 생성 완료 (7개 멀티 해상도, 클린 모서리): {ico_path}")
    
    # 3. 공용 / GUI / Linux용 1024x1024 고해상도 마스터 PNG
    # 인앱(설정창 등)에서도 모서리가 깔끔하게 떨어지도록 클린 스퀘어클(1024x1024, radius 192px)로 생성
    master_png = OUTPUT_DIR / "app_icon.png"
    clean_master = generate_clean_squircle_icon(cropped_src, 1024, radius_ratio=0.1875)
    clean_master.save(master_png, format="PNG")
    print(f"✅ 마스터 클린 PNG 생성 완료: {master_png}")
    
    print("🎉 크로스플랫폼 정밀 아이콘 패키징 완료!")


if __name__ == "__main__":
    generate_icons()
