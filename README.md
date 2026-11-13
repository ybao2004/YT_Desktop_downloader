# YouTube Desktop Downloader v3.2.2 — Python / PyQt6 (Minimal UI, Instant Launch & GPU Codec Edition)

Ứng dụng máy tính hiện đại (phiên bản **v3.2.2**) để tải Video, Audio, Shorts và Playlist YouTube với **giao diện tối giản, chuyên nghiệp (hỗ trợ cả Chế độ Sáng & Tối theo hệ thống Windows)**, **màn hình Splash Screen khởi động nhanh tức thì, hiển thị ngay trên Taskbar và không ép luôn nằm trên cùng**, **độ trễ chuyển cảnh 1 giây hoàn tất mượt mà sang cửa sổ chính**, **ngăn chặn mở nhiều cửa sổ trùng lặp (Single Instance) cấp Kernel Mutex**, **tự động đồng bộ thư mục lưu cho các tác vụ trong Hàng chờ và cho phép đổi thư mục linh hoạt từng tác vụ**, **icon ứng dụng `.ico` độ phân giải cao**, **hàng đợi tải hàng loạt kèm Tự bắt link (Clipboard Monitor), Xác minh Cookie chống Bot & Hoàn tác**, khả năng **tự động chuẩn hóa Codec (H.264 mặc định, H.265/HEVC, AV1, VP9)** tăng tốc bằng phần cứng GPU, **trang Cài đặt phân 3 tab (Chung, Cập nhật, Giới thiệu) và tự động kiểm tra bản cập nhật mới**, **giám sát tài nguyên phần cứng kèm biểu đồ sparkline 60 giây**, **cắt đoạn media**, **nhúng phụ đề/metadata**, cùng **cơ chế đóng gói 1 file `.exe` Portable Mức 2 Siêu nhẹ & cập nhật phiên bản từ xa**.

---

## Tính năng nổi bật

1. **Giao diện Tối giản & Chuyên nghiệp (Minimal Design System)**:
   - **Thanh điều hướng bên trái (Sidebar)**: Thương hiệu xếp chồng `YouTube / Downloader` căn trái, chuyển nhanh giữa 5 không gian: **Tải xuống**, **Phần cứng**, **Nhật ký**, **Hướng dẫn**, và **Cài đặt**.
   - **Chế độ màu Sáng & Tối (Light / Dark / System)**: Xây dựng trên hệ thống Design Tokens trung tính đen/trắng, tự động đồng bộ theo giao diện Windows (bao gồm cả thanh tiêu đề tối DWM trên Windows 10/11) hoặc tùy chọn cố định trong Cài đặt.
   - **Phông chữ Inter & Biểu tượng Lucide SVG**: Đóng gói sẵn phông chữ `Inter` (SIL OFL) và bộ biểu tượng vector `Lucide` (MIT License) sắc nét trên màn hình HiDPI (125% / 150%).
   - **Danh sách tác vụ tinh gọn (Hover Actions)**: Các tác vụ hiển thị trong một khung danh sách liền mạch với thanh tiến trình mảnh 4px theo màu trạng thái; toàn bộ nút thao tác trên từng hàng (Tải ngay mục đang chờ, Tạm dừng, Hủy, Mở thư mục, Xóa `✕`, và menu `⋯`) được ẩn gọn gàng và chỉ xuất hiện khi rê chuột vào hàng.
   - **Cài đặt tự động lưu (Auto-saving Settings)**: Mọi thay đổi cấu hình (chế độ màu, thư mục lưu, tải 1-click, số luồng tải đồng thời, tăng tốc phần cứng, cookies...) được lưu tự động ngay lập tức.
   - **Nhật ký thời gian thực có dấu thời gian (Timestamped Activity Log)**: Toàn bộ thông điệp phân tích, tải xuống, chuyển đổi Codec FFmpeg và lỗi trong trang **Nhật ký** đều được gắn nhãn thời gian chuẩn `[HH:MM:SS]` rõ ràng.

2. **Hàng đợi tải hàng loạt, Tự bắt link & Quản lý thông minh ngay trong tab "Tải xuống" (v3.0)**:
   - **Mặc định dán 1 link gọn nhẹ**: Thanh nhập URL chỉ giữ duy nhất nút **Tải xuống** để dán và tải nhanh 1 liên kết như truyền thống.
   - **Nút "Nhập nhiều dòng..."**: Đặt ở góc phải hàng tùy chọn định dạng; bấm để mở hộp thoại nhập nhiều liên kết cùng lúc (hỗ trợ nút **Dán thêm** nhiều lần). Khi xác nhận, các liên kết được đưa vào danh sách **Hàng chờ** (tách biệt hoàn toàn với danh sách **Đang tải**).
   - **Nút "Tự bắt link" (Mặc định tắt)**: Nằm ngay cạnh nút **Nhập nhiều dòng...**; khi bật, ứng dụng tự động theo dõi Clipboard hệ thống và đưa ngay các liên kết YouTube vừa sao chép vào danh sách **Hàng chờ**.
   - **Hộp thoại Xác minh Cookie (Anti-Bot Bypass)**: Tự động hỗ trợ dán hoặc chọn tệp `cookies.txt` (định dạng Netscape), tự động chuẩn hóa cú pháp phân cách dòng/cột để vượt qua cơ chế kiểm tra bot của YouTube mà không làm gián đoạn tải hàng loạt.
   - **Bộ lọc trạng thái 6 mục (Gần đây, Tất cả, Hàng chờ, Đang tải, Hoàn tất, Lỗi)**: Tab **Gần đây** hiển thị các mục vừa thêm trong phiên làm việc hoặc trong 24 giờ qua (là tab mặc định khi mở app); tab **Tất cả** xem trọn bộ lịch sử.
   - **Nút "Tải lại tất cả"**: Nằm trên thanh công cụ hàng đợi, tự động tải lại các mục thuộc tab trạng thái đang xem và áp dụng chính xác cấu hình đang chọn trên thanh công cụ (Định dạng, Chất lượng, Codec, Tắt tiếng, Thư mục lưu...).
   - **Hiển thị đầy đủ thông số chi tiết trên từng thẻ**: Mỗi video hiển thị chấm màu và tên trạng thái rõ ràng (`● Hàng chờ`, `● Đang tải`, `● Hoàn tất`, `● Tạm dừng`, `● Lỗi`...), cùng dòng phụ gộp đầy đủ: `Định dạng · Codec · Độ phân giải · FPS · Bitrate · Đường dẫn lưu`.
   - **Xóa 1 mục, Xóa tất cả, Hoàn tác (Undo) & Làm lại (Redo) riêng biệt từng Tab**: Dễ dàng xóa từng mục (`✕`), **Xóa tất cả** hàng đợi hoặc bấm **Hoàn tác** / **Làm lại** trên thanh công cụ. Hai nút này ghi nhớ lịch sử **độc lập theo từng tab trạng thái** (`Gần đây`, `Tất cả`, `Hàng chờ`, `Đang tải`, `Hoàn tất`, `Lỗi`), chuyển tab lập tức cập nhật lại số lượng và trạng thái khả dụng.
   - **Hệ thống Phím tắt & Chọn nhiều Video (Multi-select)**:
     - `Click`: Chọn đơn thẻ video (hiển thị màu nền nhẹ nhàng, không viền).
     - `Ctrl + Click`: Chọn hoặc bỏ chọn từng video riêng lẻ.
     - `Shift + Click`: Chọn dải video liên tục từ video trước đó đến video vừa nhấp.
     - `Delete`: Xóa các video đang chọn (đẩy vào ngăn xếp Hoàn tác của tab hiện tại).
     - `Enter`: Bắt đầu tải các video đang chọn.
     - `Space`: Phát nếu chọn 1 video đã hoàn tất; bật/tắt Tạm dừng/Tiếp tục nếu chọn các video đang tải/tạm dừng.
     - `Ctrl + Z`: Hoàn tác thao tác xóa gần nhất ở tab hiện tại.
     - `Ctrl + Shift + Z` & `Ctrl + Y`: Làm lại thao tác xóa vừa hoàn tác ở tab hiện tại.
     - `Ctrl + A`: Chọn tất cả video đang hiển thị trong tab hiện tại.
     - `Ctrl + Shift + A` / `Escape`: Hủy chọn tất cả.
     - *An toàn khi nhập liệu*: Toàn bộ phím tắt tự động nhường quyền khi con trỏ đang ở các ô nhập văn bản (`QLineEdit`, ô tìm kiếm...).

3. **Quy tắc Đặt tên File & Chuyển đổi Video Codec thông minh**:
   - **Tên file gốc nguyên bản (Mặc định)**: Tên tệp tải về lấy chính xác theo tiêu đề video gốc từ YouTube, không bị gắn hậu tố ID `[%(id)s]` gây rối mắt. Người dùng có thể bật lại tùy chọn thêm ID trong trang **Cài đặt** nếu cần.
   - **Codec chuẩn hóa (Mặc định H.264, hỗ trợ H.265/HEVC, AV1, VP9, Auto)**: Ưu tiên chọn luồng gốc từ YouTube khớp với Codec yêu cầu ở đúng độ phân giải.
   - Nếu file tải về chưa phải Codec đã chọn (ví dụ video 2K/4K trên YouTube chỉ có VP9/AV1 nhưng cần **H.264** hoặc **H.265** để xem trên mọi TV/điện thoại hoặc đưa vào phần mềm dựng phim), ứng dụng tự động kiểm tra codec (hỗ trợ fallback `ffmpeg -i` không cần `ffprobe.exe`) và chuyển đổi bằng **FFmpeg**.
   - **Tăng tốc phần cứng GPU tự động**: Tự động dò tìm và sử dụng `NVIDIA NVENC` (`h264_nvenc`, `hevc_nvenc`, `av1_nvenc`), `Intel QSV`, hoặc `AMD AMF`; tự động fallback về CPU (`libx264`, `libx265`, `libsvtav1`, `libvpx-vp9`) nếu cần.
   - **Đổi Codec theo yêu cầu**: Mở menu `⋯` (hoặc nhấp chuột phải) trên bất kỳ video nào đã tải xong để chuyển đổi sang H.264 / H.265 / AV1 / VP9 mà không cần tải lại.

4. **Tiện ích Media nâng cao**:
   - **Lưu Video không âm thanh (Nút "Tắt tiếng")**: Nằm ngay cạnh ô chọn **Codec** trên hàng cấu hình chính (mặc định tắt khi mở ứng dụng). Khi bật, ứng dụng chỉ tải luồng hình ảnh (`video-only`) không kèm âm thanh; đồng thời có thể chọn **Tắt tiếng (Xóa âm thanh)** trong menu `⋯` của các video đã tải xong để xóa âm thanh tại chỗ.
   - **Cắt đoạn Video/Audio (Clip Trimmer)**: Mở mục **Tùy chọn ▾** dưới thanh nhập link và nhập khoảng thời gian bắt đầu → kết thúc (VD: `00:45` → `04:30`).
   - **Tải & Nhúng Phụ đề (CC) + Metadata**: Tự động tải phụ đề (`vi,en...`), nhúng vào container video và nhúng thông tin Metadata.
   - **Tùy chọn Bitrate Âm thanh**: Hỗ trợ `320 kbps`, `192 kbps`, `128 kbps` khi tải Audio (`MP3`, `M4A`, `FLAC`, `Gốc`).

5. **Giám sát Phần cứng & Hệ thống Thời gian thực**:
   - **Trang "Phần cứng"**: Lưới 5 thẻ chỉ số (`CPU`, `GPU`, `RAM`, `Ổ đĩa lưu trữ`, `Băng thông mạng`) kèm **biểu đồ đường sparkline 60 giây gần nhất** và bảng thông tin chi tiết các bộ mã hóa FFmpeg khả dụng trên máy.
   - **Thanh trạng thái dưới cùng (Status Bar)**: Bên trái hiển thị **Vị trí lưu trữ** (bấm vào để chọn nhanh thư mục lưu), bên phải hiển thị tóm tắt số tác vụ và chỉ số tài nguyên hệ thống thời gian thực.

6. **Đóng gói Siêu nhẹ Single-File `.exe` (Mức 2 ~35–45 MB) kèm Icon & Màn hình Khởi động**:
   - **Màn hình Splash Screen hiện đại**: Khởi động tức thì với khung card nổi, logo YouTube bo góc đỏ, hiển thị ngay trên thanh Taskbar Windows, không ép luôn nằm trên cùng để người dùng thoải mái chuyển cửa sổ trong lúc nạp, hiển thị thanh tiến trình tải môi trường và tự động đóng sau khi cửa sổ chính sẵn sàng.
   - **Icon ứng dụng chính thức (.ico)**: Tích hợp đầy đủ các lớp độ phân giải cao (16, 32, 48, 64, 128, 256px) vào thanh tiêu đề, Taskbar Windows và file `.exe`.
   - **Trang Cài đặt chia 3 Tab chuyên nghiệp**: Tách biệt rõ ràng thành **Chung** (giao diện, đường dẫn, mã hóa, hệ thống), **Cập nhật** (kiểm tra môi trường FFmpeg/Deno, cập nhật lõi yt-dlp và cập nhật phần mềm), và **Giới thiệu** (thông tin phiên bản, tác giả `@ybao04`, giấy phép mã nguồn mở GNU GPL v3.0 và thành phần mã nguồn mở).
   - **Tự động kiểm tra bản cập nhật mới (Mặc định Bật)**: Tự động kết nối kiểm tra phiên bản mới từ GitHub Release khi khởi động.
   - **File `.exe` siêu nhẹ & giải nén nhanh**: Loại bỏ hoàn toàn các module `PyQt6` / Python không dùng đến (`opengl32sw.dll`, `Qt6Pdf.dll`, bản dịch Qt), gói gọn submodules `yt_dlp` trong `PYZ` thay vì giải nén >1.000 file `.py` rời ra ổ đĩa, biên dịch tối ưu `--optimize 2`, bỏ phụ thuộc `ffprobe.exe` (dùng `ffmpeg -i` fallback) và tách `ffmpeg.exe` + `deno.exe` khỏi file `.exe` để mở màn hình khởi động gần như tức thì.
   - **Tự động tải FFmpeg & Deno trong lần chạy đầu**: Nếu máy đích chưa có `FFmpeg` hoặc `Deno`, ứng dụng tự động tải ngầm về `~/youtube_desktop_downloader_data/bin/` ngay lần chạy đầu tiên (hoặc bấm nút **Tự động cài FFmpeg & Deno** trong Cài đặt).
   - **Cập nhật trực tuyến**: Kiểm tra phiên bản mới trực tiếp từ kho phát hành GitHub Releases mặc định ngay trong tab **Cập nhật**, kèm nút **Cập nhật lõi yt-dlp** chỉ với 1 cú nhấp chuột.

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

## Đóng gói Bản Portable 1-File `.exe` (Mức 2 Siêu nhẹ)

Nhấp đúp `build_portable.bat` hoặc chạy lệnh:

```powershell
# Mặc định (Mức 2 Siêu nhẹ ~35-45 MB): Đóng gói dist/YouTubeDesktopDownloader.exe + dist/version.json
# (Tự động tải FFmpeg & Deno vào ~/youtube_desktop_downloader_data/bin/ trong lần chạy đầu tiên)
python build_portable.py

# Tùy chọn nhúng cứng cả ffmpeg.exe + deno.exe vào trong .exe (bản All-in-One offline)
python build_portable.py --bundle-bins
```

Sau khi đóng gói, kiểm tra thư mục `dist/`:
- `dist/YouTubeDesktopDownloader.exe`: File thực thi độc lập duy nhất (~35–45 MB) có thể sao chép sang bất kỳ máy tính Windows 64-bit nào.
- `dist/version.json`: File manifest mẫu dùng cho tính năng Cập nhật phiên bản từ xa.

---

## Chạy Kiểm thử Tự động (Offline Unit & UI Tests)

Bộ kiểm thử gồm 31 test tự động bao quát toàn diện logic phân tích URL, chọn định dạng, chuẩn hóa codec, quản lý hàng đợi, hoàn tác/làm lại, xác minh cookie và đóng gói:

```powershell
# Chạy toàn bộ kiểm thử bằng pytest
pytest -v

# Hoặc chạy bằng unittest có sẵn trong Python
python -m unittest discover -s tests -v

# Kiểm tra cú pháp và biên dịch bytecode
python -m compileall -q .
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
  - `pages/`: Các trang không gian làm việc (`downloads.py`, `batch.py`, `hardware.py`, `log.py`, `guide.py`, `settings.py`).
- `ytd_app/assets/`: Tài nguyên đóng gói kèm ứng dụng:
  - `icons/*.svg`: Bộ biểu tượng Lucide (`LICENSE-lucide.txt` — MIT/ISC License).
  - `fonts/Inter-*.ttf`: Bộ phông chữ Inter (`OFL.txt` — SIL Open Font License 1.1).
- `ytd_app/engine.py`: Tích hợp `yt-dlp`, chọn luồng theo Codec, kiểm tra `ffprobe` và chuyển đổi Codec bằng `FFmpeg` (GPU/CPU).
- `ytd_app/hw_monitor.py`: Giám sát CPU, GPU, RAM, Lưu trữ, Mạng và kiểm tra thực nghiệm bộ mã hóa GPU.
- `ytd_app/updater.py`: Kiểm tra phiên bản từ xa (GitHub Releases / JSON Manifest), tải cập nhật nóng và nâng cấp `yt-dlp`.
- `ytd_app/version.py`: Quản lý phiên bản, đường dẫn dữ liệu và tự động nạp `bin/` vào `PATH`.
- `ytd_app/models.py` & `ytd_app/storage.py`: Mô hình dữ liệu (`Job`, `Settings`) và lưu trữ JSON an toàn.
- `tests/test_core.py`: Bộ unit test kiểm thử toàn diện logic và giao diện.
