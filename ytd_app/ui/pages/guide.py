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

        <p style="font-weight: 600; margin-bottom: 4px;">1. Tải nhanh hoặc Đưa vào Hàng đợi ngay trong tab "Tải xuống":</p>
        <ul style="margin-top: 4px; color: {t['text_secondary']};">
            <li>Sao chép 1 hoặc nhiều liên kết YouTube (Video thường, Shorts hoặc Playlist) và dán vào ô nhập liên kết.</li>
            <li>Chọn chế độ <b>Video</b> hoặc <b>Audio</b>, định dạng (MP4, MKV, MP3, M4A, FLAC...), <b>Chất lượng</b> (Tốt nhất, 4K, 2K, 1080p...) và <b>Codec</b>. Vị trí lưu trữ hiển thị ở góc dưới bên trái cửa sổ (bấm vào để đổi nhanh thư mục lưu).</li>
            <li>Bấm nút <b>Hàng đợi</b> để đưa các liên kết vào danh sách <i>Chờ tải</i> mà chưa tải ngay; bấm nút <b>Tải xuống</b> (hoặc nhấn phím <b>Enter</b>) để thêm liên kết đang nhập (nếu có) và bắt đầu chạy tải toàn bộ Hàng đợi ngay lập tức.</li>
        </ul>

        <p style="font-weight: 600; margin-bottom: 4px;">2. Nhập nhiều dòng, Tự bắt link &amp; Hoàn tác Hàng đợi:</p>
        <ul style="margin-top: 4px; color: {t['text_secondary']};">
            <li><b>Dán nhiều link 1 lần hoặc nhiều lần:</b> Bạn có thể dán danh sách nhiều dòng liên kết trực tiếp vào ô nhập hoặc bấm nút <b>Nhập nhiều dòng...</b> (ở góc phải hàng tùy chọn) để mở hộp thoại dán nối tiếp nhiều lần bằng nút <b>Dán thêm</b>. Ứng dụng tự động lọc bỏ văn bản không phải link YouTube và loại bỏ các link trùng lặp.</li>
            <li><b>Tự bắt link (Mặc định tắt):</b> Khi bật nút <b>Tự bắt link</b> trên hàng tùy chọn, mỗi khi bạn sao chép (Copy) liên kết YouTube ở trình duyệt, ứng dụng sẽ tự động bắt link và thêm ngay vào <b>Hàng đợi</b> (trạng thái <i>Chờ tải</i>).</li>
            <li><b>Kiểm soát tải &amp; Hoàn tác:</b> Di chuột vào từng mục trong hàng đợi để bấm nút <b>Tải ngay</b> cho riêng mục đó hoặc bấm <b>✕</b> để xóa. Nếu lỡ xóa nhầm (1 mục hoặc <b>Xóa tất cả</b>), bấm <b>Hoàn tác</b> trên thanh công cụ để khôi phục ngay lập tức.</li>
        </ul>

        <p style="font-weight: 600; margin-bottom: 4px;">3. Chuyển đổi Video Codec tự động &amp; theo yêu cầu (H.264 / H.265 / AV1 / VP9):</p>
        <ul style="margin-top: 4px; color: {t['text_secondary']};">
            <li><b>H.264 / AVC (Mặc định):</b> Tương thích 100% với mọi Tivi, điện thoại, Zalo/Messenger, Premiere Pro, CapCut, DaVinci Resolve. Với video ≤ 1080p, ứng dụng tự động ưu tiên lấy luồng H.264 gốc từ YouTube để tải cực nhanh mà không cần mã hóa lại.</li>
            <li><b>H.265 / HEVC:</b> Giữ nguyên chất lượng hình ảnh 4K/2K nhưng giảm 40%–50% dung lượng lưu trữ.</li>
            <li>Nếu video tải về từ YouTube có chuẩn gốc khác (như VP9/AV1 ở 2K/4K), ứng dụng tự động dùng <b>FFmpeg tăng tốc GPU (NVIDIA NVENC / Intel QSV / AMD AMF)</b> để chuyển sang đúng Codec bạn chọn.</li>
            <li>Với các video đã tải xong, bạn có thể rê chuột vào tác vụ, mở menu <b>⋯</b> (hoặc nhấp chuột phải) và chọn <b>Đổi Codec video (FFmpeg)</b> bất kỳ lúc nào.</li>
        </ul>

        <p style="font-weight: 600; margin-bottom: 4px;">4. Tải trọn bộ Playlist:</p>
        <ul style="margin-top: 4px; color: {t['text_secondary']};">
            <li>Mở mục <b>Tùy chọn ▾</b> ngay dưới thanh nhập liên kết và tích chọn <b>Tải cả Playlist</b> để tải hoặc chọn các video trong danh sách phát.</li>
        </ul>

        <p style="font-weight: 600; margin-bottom: 4px;">5. Cắt đoạn Video/Audio (Clip Trimmer) &amp; Nhúng Phụ đề (CC):</p>
        <ul style="margin-top: 4px; color: {t['text_secondary']};">
            <li>Bấm nút <b>Tùy chọn ▾</b> ngay dưới thanh nhập liên kết.</li>
            <li>Nhập thời gian bắt đầu và kết thúc (định dạng <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">MM:SS</code> hoặc <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">HH:MM:SS</code>, ví dụ <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">01:15</code> đến <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">04:30</code>) để chỉ cắt lấy đoạn cần thiết.</li>
            <li>Tích chọn <b>Phụ đề (CC)</b> và nhập mã ngôn ngữ (mặc định <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">vi,en</code>) để tự động nhúng phụ đề vào file video.</li>
        </ul>

        <p style="font-weight: 600; margin-bottom: 4px;">6. Danh sách Phím tắt Tiện ích (Shortcuts):</p>
        <div style="background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 10px 14px; margin-top: 6px; margin-bottom: 12px;">
            <table style="width: 100%; border-collapse: collapse; font-size: 12px; color: {t['text_secondary']};">
                <tr style="border-bottom: 1px solid {t['border']};">
                    <td style="padding: 6px 0; font-weight: 600; width: 35%; color: {t['text']};"><kbd style="background:{t['hover']}; border:1px solid {t['border_strong']}; padding:2px 6px; border-radius:4px;">Ctrl + V</kbd></td>
                    <td style="padding: 6px 0;">Dán liên kết từ Clipboard và tự động thêm vào Hàng đợi (Chờ tải).</td>
                </tr>
                <tr style="border-bottom: 1px solid {t['border']};">
                    <td style="padding: 6px 0; font-weight: 600; color: {t['text']};"><kbd style="background:{t['hover']}; border:1px solid {t['border_strong']}; padding:2px 6px; border-radius:4px;">Enter</kbd></td>
                    <td style="padding: 6px 0;">Bắt đầu tải liên kết đang nhập hoặc các video đang được chọn.</td>
                </tr>
                <tr style="border-bottom: 1px solid {t['border']};">
                    <td style="padding: 6px 0; font-weight: 600; color: {t['text']};"><kbd style="background:{t['hover']}; border:1px solid {t['border_strong']}; padding:2px 6px; border-radius:4px;">Space (Phím cách)</kbd></td>
                    <td style="padding: 6px 0;">Mở phát video (nếu đã tải xong) hoặc Tạm dừng / Tiếp tục tải mục đang chọn.</td>
                </tr>
                <tr style="border-bottom: 1px solid {t['border']};">
                    <td style="padding: 6px 0; font-weight: 600; color: {t['text']};"><kbd style="background:{t['hover']}; border:1px solid {t['border_strong']}; padding:2px 6px; border-radius:4px;">Delete</kbd> / <kbd style="background:{t['hover']}; border:1px solid {t['border_strong']}; padding:2px 6px; border-radius:4px;">Backspace</kbd></td>
                    <td style="padding: 6px 0;">Xóa các tác vụ video đang được chọn khỏi hàng đợi.</td>
                </tr>
                <tr style="border-bottom: 1px solid {t['border']};">
                    <td style="padding: 6px 0; font-weight: 600; color: {t['text']};"><kbd style="background:{t['hover']}; border:1px solid {t['border_strong']}; padding:2px 6px; border-radius:4px;">Ctrl + Z</kbd></td>
                    <td style="padding: 6px 0;"><b>Hoàn tác (Undo):</b> Khôi phục lại tác vụ vừa xóa nhầm ở tab hiện tại.</td>
                </tr>
                <tr style="border-bottom: 1px solid {t['border']};">
                    <td style="padding: 6px 0; font-weight: 600; color: {t['text']};"><kbd style="background:{t['hover']}; border:1px solid {t['border_strong']}; padding:2px 6px; border-radius:4px;">Ctrl + Y</kbd> / <kbd style="background:{t['hover']}; border:1px solid {t['border_strong']}; padding:2px 6px; border-radius:4px;">Ctrl + Shift + Z</kbd></td>
                    <td style="padding: 6px 0;"><b>Làm lại (Redo):</b> Thực hiện lại thao tác xóa vừa hoàn tác.</td>
                </tr>
                <tr style="border-bottom: 1px solid {t['border']};">
                    <td style="padding: 6px 0; font-weight: 600; color: {t['text']};"><kbd style="background:{t['hover']}; border:1px solid {t['border_strong']}; padding:2px 6px; border-radius:4px;">Ctrl + A</kbd></td>
                    <td style="padding: 6px 0;">Chọn tất cả video trong danh sách hiển thị của tab hiện tại.</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; font-weight: 600; color: {t['text']};"><kbd style="background:{t['hover']}; border:1px solid {t['border_strong']}; padding:2px 6px; border-radius:4px;">Escape</kbd> / <kbd style="background:{t['hover']}; border:1px solid {t['border_strong']}; padding:2px 6px; border-radius:4px;">Ctrl + Shift + A</kbd></td>
                    <td style="padding: 6px 0;">Hủy chọn tất cả video đang chọn.</td>
                </tr>
            </table>
        </div>

        <p style="font-weight: 600; margin-bottom: 4px;">7. Chia sẻ phần mềm sang máy tính khác:</p>
        <ul style="margin-top: 4px; color: {t['text_secondary']};">
            <li>Phần mềm được đóng gói thành <b>1 file <code style="background:{t['hover']}; padding:1px 5px; border-radius:4px;">.exe</code> Portable duy nhất</b> (~35–45 MB), tự động thiết lập FFmpeg &amp; Deno trong lần mở đầu tiên.</li>
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
