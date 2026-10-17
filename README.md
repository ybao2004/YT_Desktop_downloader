# YouTube Desktop Downloader — Python / PyQt6 (Minimal UI & GPU Codec Edition)

Ứng dụng máy tính hiện đại để tải Video, Audio, Shorts và Playlist YouTube với **giao diện tối giản, chuyên nghiệp (hỗ trợ cả Chế độ Sáng & Tối theo hệ thống Windows)**, khả năng **tự động chuẩn hóa Codec (H.264 mặc định, H.265/HEVC, AV1, VP9)** tăng tốc bằng phần cứng GPU, **giám sát tài nguyên phần cứng kèm biểu đồ sparkline 60 giây**, **cắt đoạn media**, **nhúng phụ đề/metadata**, cùng **cơ chế đóng gói 1 file `.exe` Portable & cập nhật phiên bản từ xa**.

---

## Tính năng nổi bật

1. **Giao diện Tối giản & Chuyên nghiệp (Minimal Design System)**:
   - **Thanh điều hướng bên trái (Sidebar)**: Thương hiệu xếp chồng `YouTube / Downloader` căn trái, chuyển nhanh giữa 5 không gian: **Tải xuống**, **Phần cứng**, **Nhật ký**, **Hướng dẫn**, và **Cài đặt**.
   - **Chế độ màu Sáng & Tối (Light / Dark / System)**: Xây dựng trên hệ thống Design Tokens trung tính đen/trắng, tự động đồng bộ theo giao diện Windows (bao gồm cả thanh tiêu đề tối DWM trên Windows 10/11) hoặc tùy chọn cố định trong Cài đặt.
   - **Phông chữ Inter & Biểu tượng Lucide SVG**: Đóng gói sẵn phông chữ `Inter` (SIL OFL) và bộ biểu tượng vector `Lucide` (MIT License) sắc nét trên màn hình HiDPI (125% / 150%).
   - **Danh sách tác vụ tinh gọn (Hover Actions)**: Các tác vụ hiển thị trong một khung danh sách liền mạch với thanh tiến trình mảnh 4px theo màu trạng thái; nút thao tác nhanh và menu `⋯` chỉ xuất hiện khi rê chuột vào hàng (hoặc nhấp chuột phải).
   - **Cài đặt tự động lưu (Auto-saving Settings)**: Mọi thay đổi cấu hình (chế độ màu, thư mục lưu, tải 1-click, số luồng tải đồng thời, tăng tốc phần cứng, cookies...) được lưu tự động ngay lập tức.
   - **Nhật ký thời gian thực có dấu thời gian (Timestamped Activity Log)**: Toàn bộ thông điệp phân tích, tải xuống, chuyển đổi Codec FFmpeg và lỗi trong trang **Nhật ký** đều được gắn nhãn thời gian chuẩn `[HH:MM:SS]` rõ ràng.

2. **Quy tắc Đặt tên File & Chuyển đổi Video Codec thông minh**:
   - **Tên file gốc nguyên bản (Mặc định)**: Tên tệp tải về lấy chính xác theo tiêu đề video gốc từ YouTube, không bị gắn hậu tố ID `[%(id)s]` gây rối mắt. Người dùng có thể bật lại tùy chọn thêm ID trong trang **Cài đặt** nếu cần.
   - **Codec chuẩn hóa (Mặc định H.264, hỗ trợ H.265/HEVC, AV1, VP9, Auto)**: Ưu tiên chọn luồng gốc từ YouTube khớp với Codec yêu cầu ở đúng độ phân giải.
   - Nếu file tải về chưa phải Codec đã chọn (ví dụ video 2K/4K trên YouTube chỉ có VP9/AV1 nhưng cần **H.264** hoặc **H.265** để xem trên mọi TV/điện thoại hoặc đưa vào phần mềm dựng phim), ứng dụng tự động kiểm tra bằng `ffprobe` và chuyển đổi bằng **FFmpeg**.
   - **Tăng tốc phần cứng GPU tự động**: Tự động dò tìm và sử dụng `NVIDIA NVENC` (`h264_nvenc`, `hevc_nvenc`, `av1_nvenc`), `Intel QSV`, hoặc `AMD AMF`; tự động fallback về CPU (`libx264`, `libx265`, `libsvtav1`, `libvpx-vp9`) nếu cần.
   - **Đổi Codec theo yêu cầu**: Mở menu `⋯` (hoặc nhấp chuột phải) trên bất kỳ video nào đã tải xong để chuyển đổi sang H.264 / H.265 / AV1 / VP9 mà không cần tải lại.

3. **Tiện ích Media nâng cao**:
   - **Cắt đoạn Video/Audio (Clip Trimmer)**: Mở mục **Tùy chọn ▾** dưới thanh nhập link và nhập khoảng thời gian bắt đầu → kết thúc (VD: `00:45` → `04:30`).
   - **Tải & Nhúng Phụ đề (CC) + Metadata**: Tự động tải phụ đề (`vi,en...`), nhúng vào container video và nhúng thông tin Metadata.
   - **Tùy chọn Bitrate Âm thanh**: Hỗ trợ `320 kbps`, `192 kbps`, `128 kbps` khi tải Audio (`MP3`, `M4A`, `FLAC`, `Gốc`).

4. **Giám sát Phần cứng & Hệ thống Thời gian thực**:
   - **Trang "Phần cứng"**: Lưới 5 thẻ chỉ số (`CPU`, `GPU`, `RAM`, `Ổ đĩa lưu trữ`, `Băng thông mạng`) kèm **biểu đồ đường sparkline 60 giây gần nhất** và bảng thông tin chi tiết các bộ mã hóa FFmpeg khả dụng trên máy.
   - **Thanh trạng thái (Status Bar)**: Hiển thị tóm tắt số tác vụ và chỉ số tài nguyên gọn nhẹ ở cạnh dưới cửa sổ.

5. **Đóng gói Single-File `.exe` & Cập nhật Phiên bản Từ xa**:
   - **1 file `.exe` All-in-One**: Nhúng sẵn Python, PyQt6, `yt-dlp`, `yt-dlp-ejs`, `FFmpeg`, `FFprobe`, `Deno`, phông chữ `Inter` và bộ icon `Lucide`.
   - **Cập nhật trực tuyến**: Kiểm tra phiên bản mới qua GitHub Releases hoặc URL `version.json` ngay trong trang **Cài đặt → Môi trường & Cập nhật**, kèm nút **Cập nhật lõi yt-dlp** chỉ với 1 cú nhấp chuột.

---

## Cài đặt & Chạy từ Mã nguồn (Windows)

1. Cài Python 3.11+ và cài đặt FFmpeg + Deno:
   ```powershell
   winget install Gyan.FFmpeg
   winget install DenoLand.Deno
   ```
2. Nhấp đúp `run_windows.bat` hoặc chạy trong PowerShell:
   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe main.py
   ```

---

## Đóng gói Bản Portable 1-File `.exe`

Nhấp đúp `build_portable.bat` hoặc chạy lệnh:

```powershell
# Đóng gói duy nhất 1 file dist/YouTubeDesktopDownloader.exe (kèm FFmpeg, FFprobe, Deno, assets) + dist/version.json
python build_portable.py

# Đóng gói nhanh không nhúng FFmpeg/Deno (dùng để kiểm thử nhanh giao diện)
python build_portable.py --skip-bins
```

Sau khi đóng gói, kiểm tra thư mục `dist/`:
- `dist/YouTubeDesktopDownloader.exe`: File thực thi độc lập duy nhất có thể sao chép sang bất kỳ máy tính Windows 64-bit nào.
- `dist/version.json`: File manifest mẫu dùng cho tính năng Cập nhật phiên bản từ xa.

---

## Chạy Kiểm thử Tự động (Offline Unit & UI Tests)

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q .
```

---

## Cấu trúc Dự án

- `main.py`: Entrypoint khởi chạy ứng dụng (`setup_app` + `MainWindow`).
- `build_portable.py` / `build_portable.bat` / `YouTubeDesktopDownloader.spec`: Công cụ đóng gói Single-File `.exe` và sinh manifest cập nhật.
- `ytd_app/theme.py`: Hệ thống Design Tokens (`LIGHT` / `DARK`), trình sinh QSS/QPalette và `ThemeManager`.
- `ytd_app/ui/`: Package giao diện người dùng PyQt6 đã tách mô-đun:
  - `app.py`: Khởi tạo style Fusion, nạp phông chữ `Inter` và áp dụng chủ đề màu.
  - `icons.py`: Trình nạp và tô màu động biểu tượng vector `Lucide SVG` có bộ nhớ đệm HiDPI.
  - `win_effects.py`: Tích hợp thanh tiêu đề tối gốc của Windows (DWM API).
  - `main_window.py`: Cửa sổ chính `MainWindow` điều phối hàng đợi, worker và các trang.
  - `widgets/`: Các thành phần tái sử dụng (`Sidebar`, `JobRow`, `SegmentedControl`, `MetricCard`, `SparklineWidget`, `FolderChip`, `SectionCard`, `SettingRow`).
  - `pages/`: Các trang không gian làm việc (`downloads.py`, `hardware.py`, `log.py`, `guide.py`, `settings.py`).
- `ytd_app/assets/`: Tài nguyên đóng gói kèm ứng dụng:
  - `icons/*.svg`: Bộ biểu tượng Lucide (`LICENSE-lucide.txt` — MIT/ISC License).
  - `fonts/Inter-*.ttf`: Bộ phông chữ Inter (`OFL.txt` — SIL Open Font License 1.1).
- `ytd_app/engine.py`: Tích hợp `yt-dlp`, chọn luồng theo Codec, kiểm tra `ffprobe` và chuyển đổi Codec bằng `FFmpeg` (GPU/CPU).
- `ytd_app/hw_monitor.py`: Giám sát CPU, GPU, RAM, Lưu trữ, Mạng và kiểm tra thực nghiệm bộ mã hóa GPU.
- `ytd_app/updater.py`: Kiểm tra phiên bản từ xa (GitHub Releases / JSON Manifest), tải cập nhật nóng và nâng cấp `yt-dlp`.
- `ytd_app/version.py`: Quản lý phiên bản, đường dẫn dữ liệu và tự động nạp `bin/` vào `PATH`.
- `ytd_app/models.py` & `ytd_app/storage.py`: Mô hình dữ liệu (`Job`, `Settings`) và lưu trữ JSON an toàn.
- `tests/test_core.py`: Bộ unit test kiểm thử toàn diện logic và giao diện.
