"""User guide page builder preserving full documentation content with theme-aware styling."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ...theme import theme_manager

if TYPE_CHECKING:
    from ..main_window import MainWindow


def _guide_html(t: dict[str, str]) -> str:
    return f"""
    <div style="font-family: 'Inter', 'Segoe UI', sans-serif; color: {t['text']}; line-height: 1.6; font-size: 13px;">
        <h3 style="color: {t['text']}; margin-top: 0; font-weight: 600;">
            Hướng dẫn sử dụng YouTube Desktop Downloader
        </h3>

        <p style="font-weight: 600; margin-bottom: 4px;">1. Tải nhanh Video hoặc Nhạc chỉ với 1-Click:</p>
        <ul style="margin-top: 4px; color: {t['text_secondary']};">
            <li>Sao chép liên kết YouTube (Video thường, Shorts hoặc Playlist) và bấm biểu tượng <b>Dán</b> ở bên phải ô nhập liên kết.</li>
            <li>Chọn chế độ <b>Video</b> hoặc <b>Audio</b>, định dạng (MP4, MKV, MP3, M4A, FLAC...), <b>Chất lượng</b> (Tốt nhất, 4K, 2K, 1080p...) và <b>Codec</b>.</li>
            <li>Khi bật <b>Tải 1-click</b> (trong Cài đặt), bấm <b>Tải xuống</b> (hoặc nhấn phím <b>Enter</b>) sẽ đưa thẳng video vào hàng đợi và tải ngay lập tức.</li>
        </ul>

        <p style="font-weight: 600; margin-bottom: 4px;">2. Chuyển đổi Video Codec tự động &amp; theo yêu cầu (H.264 / H.265 / AV1 / VP9):</p>
        <ul style="margin-top: 4px; color: {t['text_secondary']};">
            <li><b>H.264 / AVC (Mặc định):</b> Tương thích 100% với mọi Tivi, điện thoại, Zalo/Messenger, Premiere Pro, CapCut, DaVinci Resolve. Với video ≤ 1080p, ứng dụng tự động ưu tiên lấy luồng H.264 gốc từ YouTube để tải cực nhanh mà không cần mã hóa lại.</li>
            <li><b>H.265 / HEVC:</b> Giữ nguyên chất lượng hình ảnh 4K/2K nhưng giảm 40%–50% dung lượng lưu trữ.</li>
            <li>Nếu video tải về từ YouTube có chuẩn gốc khác (như VP9/AV1 ở 2K/4K), ứng dụng tự động dùng <b>FFmpeg tăng tốc GPU (NVIDIA NVENC / Intel QSV / AMD AMF)</b> để chuyển sang đúng Codec bạn chọn.</li>
            <li>Với các video đã tải xong, bạn có thể rê chuột vào tác vụ, mở menu <b>⋯</b> (hoặc nhấp chuột phải) và chọn <b>Đổi Codec video (FFmpeg)</b> bất kỳ lúc nào.</li>
        </ul>

        <p style="font-weight: 600; margin-bottom: 4px;">3. Phân tích liên kết &amp; Chọn từng video trong Playlist:</p>
        <ul style="margin-top: 4px; color: {t['text_secondary']};">
            <li>Bấm nút <b>Phân tích</b> để xem trước ảnh thu nhỏ (Thumbnail), tên kênh, thời lượng và bảng toàn bộ các luồng Format ID gốc.</li>
            <li>Khi tải <b>Playlist</b>: Mở mục <b>Tùy chọn ▾</b>, tích chọn <b>Tải cả Playlist</b> rồi bấm <b>Phân tích</b> để tích chọn hoặc bỏ chọn từng video cụ thể trước khi tải.</li>
        </ul>

        <p style="font-weight: 600; margin-bottom: 4px;">4. Cắt đoạn Video/Audio (Clip Trimmer) &amp; Nhúng Phụ đề (CC):</p>
        <ul style="margin-top: 4px; color: {t['text_secondary']};">
            <li>Bấm nút <b>Tùy chọn ▾</b> ngay dưới thanh nhập liên kết.</li>
            <li>Nhập thời gian bắt đầu và kết thúc (định dạng <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">MM:SS</code> hoặc <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">HH:MM:SS</code>, ví dụ <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">01:15</code> đến <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">04:30</code>) để chỉ cắt lấy đoạn cần thiết.</li>
            <li>Tích chọn <b>Phụ đề (CC)</b> và nhập mã ngôn ngữ (mặc định <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">vi,en</code>) để tự động nhúng phụ đề vào file video.</li>
        </ul>

        <p style="font-weight: 600; margin-bottom: 4px;">5. Chia sẻ phần mềm sang máy tính khác:</p>
        <ul style="margin-top: 4px; color: {t['text_secondary']};">
            <li>Phần mềm được đóng gói thành <b>1 file <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">.exe</code> duy nhất</b> (đã nhúng sẵn FFmpeg, FFprobe, Deno và yt-dlp).</li>
            <li>Khi gửi file <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">.exe</code> sang máy tính khác, người nhận chỉ cần mở lên dùng ngay mà không cần cài đặt thêm bất kỳ công cụ nào.</li>
        </ul>
    </div>
    """


def build_guide_page(win: MainWindow) -> QWidget:
    page = QWidget()
    page.setObjectName("pageContainer")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 20, 24, 16)
    layout.setSpacing(12)

    header = QHBoxLayout()
    title = QLabel("Hướng dẫn")
    title.setObjectName("pageTitle")
    header.addWidget(title)
    sub = QLabel("Tài liệu hướng dẫn sử dụng chi tiết")
    sub.setObjectName("mutedLabel")
    header.addSpacing(8)
    header.addWidget(sub)
    header.addStretch(1)
    layout.addLayout(header)

    win.guide_browser = QTextBrowser()
    win.guide_browser.setOpenExternalLinks(True)

    def _refresh_guide(*_args) -> None:
        win.guide_browser.setHtml(_guide_html(theme_manager().tokens))

    _refresh_guide()
    theme_manager().changed.connect(_refresh_guide)
    layout.addWidget(win.guide_browser, 1)
    return page
