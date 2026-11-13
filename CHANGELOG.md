# Nhật ký Thay đổi (Changelog)

Toàn bộ các thay đổi quan trọng của dự án **YouTube Desktop Downloader** được ghi lại trong tài liệu này theo chuẩn [Keep a Changelog](https://keepachangelog.com/vi/1.0.0/) và tuân thủ [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [3.2.1] - 2026-11-13

### Đã tối ưu (Optimized)
- **Tăng tốc độ mở Màn hình Khởi động (Splash Screen) và giảm tải giải nén `.exe`**:
  - Loại bỏ chuỗi fallback font QSS dư thừa (`'Segoe UI Variable Text', 'Segoe UI', -apple-system, sans-serif`) trong `splash.py` và `theme.py` vốn gây quét lại toàn bộ phông chữ hệ thống (~3.1 giây) khi vẽ khung hình Splash đầu tiên.
  - Trì hoãn nạp các widget nặng (`ytd_app.ui.widgets`) qua `__getattr__` trong `ytd_app/ui/__init__.py`, nhập trực tiếp `splash`/`app` trong `main.py`, và bỏ qua `QLocalSocket` probe dư thừa trên Windows khi Mutex cấp Kernel đã xác nhận tiến trình chính.
  - Tối ưu đóng gói PyInstaller (`YouTubeDesktopDownloader.spec` & `build_portable.py`): chuyển sang `--collect-submodules` + `--collect-data` (loại bỏ >1.000 file `.py` rời của `yt_dlp` khỏi giải nén ra đĩa mỗi lần mở app) và loại bỏ `opengl32sw.dll`, `Qt6Pdf.dll`, `qpdf.dll`, cùng 96 tệp bản dịch Qt không dùng đến.

### Đã thay đổi (Changed)
- **Màn hình Khởi động hiển thị trên Taskbar & không luôn nằm trên cùng**:
  - Đổi cờ cửa sổ `SplashScreen` từ `SplashScreen | WindowStaysOnTopHint` sang `Window | FramelessWindowHint | WindowMinimizeButtonHint` kèm tiêu đề và icon ứng dụng, giúp cửa sổ khởi động xuất hiện ngay trên thanh Taskbar Windows và không đè cứng lên các cửa sổ khác.
- **Tinh gọn Tab Cập nhật trong Cài đặt**:
  - Xóa bỏ ô nhập **Nguồn cập nhật (GitHub / Manifest URL)** trên giao diện Tab Cập nhật và handler liên quan; ứng dụng luôn kiểm tra trực tiếp từ kho phát hành mặc định `ybao2004/YT_Desktop_downloader`.

---

## [3.2.0] - 2026-11-01

### Đã thêm (Added)
- **Cơ chế Khóa Độc bản Cấp Kernel (Atomic Windows Named Mutex Single Instance)**:
  - Ngăn chặn hoàn toàn việc mở 2 hoặc nhiều cửa sổ cùng lúc kể cả khi người dùng nhấp đúp liên tục hoặc khởi chạy đồng thời nhiều tiến trình.
  - Sử dụng Windows Kernel Mutex `Local\YouTubeDesktopDownloader_SingleInstance_Mutex_v32` kiểm tra ngay tại microsecond đầu tiên khởi động.
  - Khởi chạy Socket Server lắng nghe tức thời ngay khi khởi tạo ứng dụng, loại bỏ hoàn toàn khoảng trễ 3-4 giây trước đây.
  - Tự động ủy quyền `AllowSetForegroundWindow` và sử dụng Win32 API (`ShowWindow(SW_RESTORE)` + `SetForegroundWindow`) để đưa cửa sổ hiện có lên trên cùng màn hình ngay lập tức khi phát hiện mở trùng lặp.

---

## [3.1.1] - 2026-10-26

### Đã thay đổi (Changed)
- **Tái cấu trúc bố cục Tab Cập nhật**:
  - Chuyển toàn bộ các nút thao tác (`Kiểm tra lại môi trường`, `Tự động cài FFmpeg & Deno`, `Cập nhật lõi yt-dlp`, `Kiểm tra cập nhật`, `Tải & Cập nhật ngay`) lên **phía trên** phần ghi chú phát hành.
  - Mở rộng khung hiển thị ghi chú phát hành (`upd_notes_box`) với chiều cao tối thiểu 180px, giúp người dùng theo dõi trọn vẹn thông tin phiên bản mới và changelog mà không bị che khuất.
- **Khắc phục lỗi hiển thị & Tinh gọn**:
  - Escape ký tự `&` trong các nút bấm tránh bị Qt diễn giải thành phím tắt mnemonic `_`.
  - Tắt chữ phần trăm hiển thị đè trong thanh tiến trình tải cập nhật mảnh 6px.
  - Gom toàn bộ tính năng kiểm tra cập nhật về duy nhất Tab Cập nhật.

---

## [3.1.0] - 2026-10-26

### Đã tối ưu (Optimized)
- **Tốc độ mở màn hình khởi động tức thì (Instant Splash Launch)**:
  - Loại bỏ hoàn toàn rasterization drop shadow nặng (~1.4s) trên cửa sổ Splash trong suốt; thay bằng viền card sắc nét chuẩn thiết kế hiện đại.
  - Tách quá trình nạp CSS stylesheet 600 dòng của ứng dụng: chỉ nạp bảng màu Palette siêu nhẹ trước khi hiện Splash, đẩy việc nạp toàn bộ Stylesheet ra phía sau khi Splash đã hiển thị. Nhờ đó, thời gian từ lúc bấm chuột vào `.exe` đến khi Màn hình Khởi động xuất hiện giảm từ ~4.8 giây xuống còn **~1.7 giây** (gần như tức thì).
- **Chuyển cảnh mượt mà có chủ đích (Intentional Splash Transition)**:
  - Sau khi các tiến trình khởi tạo hoàn tất đạt 100% ("Hoàn tất!"), ứng dụng giữ màn hình Splash thêm đúng **1.0 giây** qua `QTimer.singleShot(1000)` trước khi mở màn hình chính, mang lại cảm giác mượt mà, chuyên nghiệp và không bị giật/chớp tắt đột ngột.
  - Single-Instance socket probe được tinh gọn từ 120ms xuống 50ms, tăng tốc độ phản hồi khi mở trùng lặp.
- **Tối ưu hóa khởi động danh sách hàng đợi**:
  - Thêm cờ `batch_init=True` khi nạp hàng trăm tác vụ từ file lưu trữ, loại bỏ kiểm tra trùng lặp $O(N^2)$ và chuyển sang nạp ảnh bìa (thumbnail) lười (lazy-load) trong luồng nền.

### Đã sửa (Fixed)
- **B1**: Sửa lỗi `TypeError: ensure_runtime_tools_async() got an unexpected keyword argument 'parent'` trong `main_window.py`.
- **B2**: Khắc phục triệt để Zombie Job (tác vụ bị treo trạng thái `downloading` / `processing` khi ứng dụng bị tắt đột ngột) trong `storage.py`.
- **B3**: Sửa lỗi phục hồi và hủy tác vụ Tạm dừng (`paused`) không được theo dõi trong `active_threads`.
- **B4**: Loại bỏ việc kiểm tra môi trường chạy 2 lần liên tiếp (`environment_report` & `ensure_runtime_tools_async`).
- **B5**: Khử trùng lặp tải ảnh bìa qua mạng (`_pending_thumbs` set trong `main_window.py`).
- **B6**: Loại bỏ hiện tượng chớp tắt chế độ màu (Theme flickering) bằng cơ chế đọc nhanh cấu hình `peek_theme_mode()`.

---

## [3.0.0] - 2026-10-21

### Đã sửa (Fixed)
- **Sửa lỗi thiếu `Path` trong `batch.py`**: Khắc phục lỗi `NameError: name 'Path' is not defined` tại các vị trí nạp đường dẫn cookie, duyệt tệp `cookies.txt` và nạp danh sách liên kết từ tệp văn bản.
- **Sửa lỗi kiểm thử phiên bản**: Cập nhật khẳng định phiên bản trong `tests/test_core.py` đồng bộ với `APP_VERSION = "3.0"`, giúp 100% kiểm thử tự động vượt qua (29/29 tests passed).
- **Đồng bộ siêu dữ liệu Windows PE**: Cập nhật `version_info.txt` từ `2.9.0.0` lên `3.0.0.0` để file thực thi `.exe` hiển thị đúng phiên bản trong thuộc tính Windows Explorer.
- **Sửa quy tắc `.gitignore` cho file `.spec`**: Thêm ngoại lệ `!YouTubeDesktopDownloader.spec` để bảo toàn file cấu hình đóng gói PyInstaller trong quản lý phiên bản.
- **Dọn dẹp mã nguồn & Cảnh báo Lint**:
  - Loại bỏ các biến thừa không dùng `is_retryable`, `is_removable` trong `job_row.py`.
  - Loại bỏ tiền tố `f` thừa trong các chuỗi định dạng không có tham số tại `engine.py`.
  - Dọn dẹp các import không sử dụng tại `models.py`, `splash.py`, `metric_card.py`, `main_window.py` và `batch.py`.
  - Khai báo tường minh `__all__ = ["__version__"]` trong `ytd_app/__init__.py`.

### Đã thêm (Added)
- **Kiểm thử hồi quy cho chuẩn hóa đường dẫn Cookie**: Bổ sung ca kiểm thử `test_version_consistency_and_cookie_path_normalization` kiểm tra tự động tính nhất quán phiên bản giữa các tệp mã nguồn, manifest `dist/version.json`, tài nguyên PE và kiểm tra xử lý đường dẫn tệp cookie có dấu ngoặc kép hoặc khoảng trắng.
- **Tài liệu Changelog**: Tạo tệp `CHANGELOG.md` ghi nhận chi tiết lịch sử nâng cấp và tính năng qua các phiên bản.

### Đã thay đổi (Changed)
- **Đồng bộ tài liệu `README.md` lên v3.0**: Cập nhật toàn bộ các đề mục, mô tả tính năng đóng gói Mức 2 Siêu nhẹ (~35–45 MB), cơ chế nạp công cụ nền FFmpeg & Deno, hướng dẫn kiểm thử tự động bằng `pytest`.
- **Cập nhật trang Hướng dẫn (`guide.py`)**: Diễn giải chính xác cơ chế đóng gói Portable 1 file `.exe` duy nhất siêu nhẹ.

---

## [2.9.0] - 2026-09-15

### Đã thêm (Added)
- **Màn hình Splash Screen hiện đại**: Hiển thị tức thì khung card nổi kèm thanh tiến trình tải môi trường khi nhấp mở phần mềm.
- **Cơ chế Single Instance IPC**: Ngăn chặn người dùng mở nhiều cửa sổ trùng lặp gây xung đột cổng mạng hoặc ghi đè file tải; tự động kích hoạt cửa sổ đang chạy lên nền trước khi có yêu cầu mở mới.
- **Đồng bộ thư mục lưu trữ thông minh**: Tự động chuẩn hóa và cập nhật đường dẫn tải xuống cho toàn bộ các tác vụ trong Hàng chờ khi người dùng đổi thư mục lưu.
- **Biểu tượng ứng dụng đa độ phân giải (`app_icon.ico`)**: Đóng gói đầy đủ các kích thước 16x16, 32x32, 48x48, 64x64, 128x128 và 256x256 px.

---

## [2.8.0] - 2026-08-30

### Đã thêm (Added)
- **Giám sát phần cứng thời gian thực với Sparkline 60 giây**: Biểu đồ mượt mà hiển thị mức sử dụng CPU, RAM, GPU, Băng thông mạng và Dung lượng ổ đĩa.
- **Tự động dò tìm & kích hoạt bộ mã hóa GPU**: Tích hợp NVIDIA NVENC, Intel QuickSync Video (QSV), AMD AMF với cơ chế thử nghiệm không nghẽn luồng.
- **Cơ chế Cập nhật nóng & Nâng cấp yt-dlp trong bộ nhớ**: Nâng cấp lõi `yt-dlp` qua gói Wheel PyPI trực tiếp mà không cần cài Python trên máy người dùng cuối.
- **Tạo Manifest cập nhật từ xa (`dist/version.json`)**: Hỗ trợ triển khai cập nhật phiên bản ứng dụng tự động qua GitHub Releases.

---

## [2.0.0] - 2026-07-10

### Đã thêm (Added)
- **Tái thiết kế toàn diện giao diện (Minimal Design System)**:
  - Thanh điều hướng bên trái (Sidebar) xếp chồng gọn gàng 208px.
  - Thiết kế trung tính chuẩn hỗ trợ Chế độ màu Sáng (Light) & Tối (Dark) theo hệ thống Windows.
  - Phông chữ Inter (SIL OFL) và bộ biểu tượng Lucide SVG sắc nét trên màn hình HiDPI.
- **Hàng đợi tải hàng loạt & Tự bắt link (Clipboard Auto-capture)**:
  - Hộp thoại nhập nhiều liên kết với nút "Dán thêm" nối tiếp.
  - Bộ lọc 6 tab trạng thái: Gần đây, Tất cả, Hàng chờ, Đang tải, Hoàn tất, Lỗi.
  - Ngăn xếp Hoàn tác (Undo) và Làm lại (Redo) độc lập theo từng tab.
  - Hệ thống phím tắt đa dạng: `Ctrl+V`, `Ctrl+Z`, `Ctrl+Y`, `Ctrl+A`, `Delete`, `Space`, `Enter`.

---

## [1.0.0] - 2026-05-01

### Đã thêm (Added)
- Phiên bản đầu tiên hỗ trợ tải Video, Audio, Shorts và Playlist YouTube bằng PyQt6 và `yt-dlp`.
- Hỗ trợ chọn định dạng MP4, MKV, WebM, MP3, M4A, FLAC.
- Cắt đoạn video và nhúng metadata cơ bản.
