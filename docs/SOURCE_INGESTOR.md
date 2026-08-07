# Bộ tải nguồn

## Luồng xử lý

`RealSourceIngestor` kiểm tra một YouTube URL, tải một video và thumbnail tốt nhất bằng yt-dlp, kiểm tra `source.mp4` bằng ffprobe, chuẩn hóa thumbnail bằng Pillow rồi ghi nguyên tử `metadata.json`.

```text
YouTube URL
  -> kiểm tra URL và dependency
  -> yt-dlp tải + báo tiến độ
  -> FFmpeg merge/remux thành source.mp4
  -> ffprobe kiểm tra
  -> Pillow chuẩn hóa JPEG
  -> ghi nguyên tử metadata.json
```

## Chiến lược định dạng

Thứ tự ưu tiên yt-dlp:

```text
bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]
best[height<=1080][ext=mp4]
best[height<=1080]
```

Độ cao tối đa mặc định 1080 và có thể cấu hình. Nguồn thấp hơn được giữ nguyên, không upscale. Stream rời được merge; fallback không phải MP4 được remux sang MP4 bằng FFmpeg. Playlist, subtitle, comment và tải nhiều video bị tắt.

## Output workspace

```text
workspace/<job_id>/source/
|-- source.mp4
|-- thumbnail.jpg
`-- metadata.json
```

File tạm yt-dlp nằm trong thư mục source riêng của job. File dở bị xóa sau hủy hoặc download lỗi. `source.mp4` đã hợp lệ được giữ nếu bước thumbnail sau đó lỗi.

## Metadata và kiểm tra

Schema version 1 lưu job/video ID, URL, tiêu đề, kênh, thời lượng, ngày upload, đường dẫn tương đối, kích thước, FPS, codec, dung lượng, thời điểm tải và version yt-dlp/FFmpeg. Ghi qua `metadata.json.tmp` rồi replace nguyên tử.

ffprobe phải đọc được video stream có thời lượng, kích thước và FPS dương. Audio được ghi nhận nhưng không bắt buộc. Pillow phải đọc được thumbnail. PNG, WebP và JPEG được chuyển thành `thumbnail.jpg` mà không crop hoặc resize.

## Hủy và lỗi

`threading.Event` được kiểm tra trước khi tải và trong progress hook của yt-dlp. `JobCancelled` dừng quy trình và ngăn stage sau. File `.part`, `.ytdl`, file tạm hoặc source mơ hồ bị xóa.

Video private, unavailable, deleted, age-restricted, cần đăng nhập, lỗi mạng/timeout/dependency/merge/thumbnail/ffprobe/write được ánh xạ thành lỗi tiếng Việt an toàn. Exception và traceback kỹ thuật chỉ ở `pipeline.log`.

## Cấu hình

| Biến | Mặc định | Ý nghĩa |
|---|---:|---|
| `PIPELINE_WORKSPACE` | `workspace` | Thư mục gốc job |
| `SOURCE_MAX_DURATION_SECONDS` | `0` | Thời lượng tối đa; `0` là không giới hạn |
| `SOURCE_DOWNLOAD_TIMEOUT_SECONDS` | `1800` | Timeout download |
| `SOURCE_MAX_HEIGHT` | `1080` | Độ cao nguồn ưu tiên tối đa |
| `YTDLP_MODE` | `python` | Cách chạy yt-dlp được hỗ trợ |
| `FFMPEG_PATH` | `ffmpeg` | Lệnh hoặc đường dẫn FFmpeg |
| `FFPROBE_PATH` | `ffprobe` | Lệnh hoặc đường dẫn ffprobe |

## API và smoke test

`GET /api/jobs/{job_id}/assets/thumbnail` chỉ trả JPEG đã kiểm tra của job, không phải filesystem endpoint tổng quát.

Lệnh sau tải mạng thật và không nằm trong pytest:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_source.py "https://www.youtube.com/watch?v=VIDEO_ID"
```
