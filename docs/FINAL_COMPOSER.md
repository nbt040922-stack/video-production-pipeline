# Bộ ghép video cuối

`FinalComposer` là stage backend cuối. Nó chỉ đọc artifact đã hoàn tất, không sửa input:

```text
hook/final_hook.mp4
          +
review/review.mp4
          |
          v
FFmpeg FinalComposer
          |
          v
final/final_video.mp4
```

## Chiến lược

ffprobe kiểm tra cả hai input trước khi ghép. Nếu video codec, audio codec, resolution và frame rate giống nhau, FFmpeg concat demuxer ghép Hook trước, Review sau bằng stream copy; giữ chất lượng và tránh encode lần hai.

Nếu thông số khác nhau hoặc stream-copy tạo file lỗi, Composer retry một lần bằng H.264/AAC, 1920×1080, 30 FPS, stereo 48 kHz. Video được scale và pad, không đổi tỷ lệ khung hình. Thời lượng final phải nằm trong sai số 3% hoặc một giây so với tổng hai input.

## Output

```text
workspace/<job_id>/final/
|-- final_video.mp4
|-- metadata.json
|-- compose_report.json
|-- composer.log
`-- ffmpeg-progress.log
```

`metadata.json` lưu thời lượng, resolution, frame rate, codec, kích thước, đường dẫn tương đối và chiến lược đã dùng. `compose_report.json` ghi probe input, lần concat, lý do fallback và probe output. Log được giữ sau failed/cancelled; file render và concat-list tạm bị xóa sau thành công.

## Tiến độ và hủy

FFmpeg ghi thời gian render máy đọc được vào `ffmpeg-progress.log`; Compose card tính tiến độ từ tổng thời lượng input. Hủy sẽ dừng FFmpeg đang chạy, không đụng Hook, Review và log chẩn đoán. Job chỉ completed sau khi Validate chấp nhận final file.

## Cấu hình

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `FFMPEG_PATH` | `ffmpeg` | Lệnh hoặc đường dẫn FFmpeg |
| `FFPROBE_PATH` | `ffprobe` | Lệnh hoặc đường dẫn ffprobe |
| `FINAL_COMPOSER_TIMEOUT_SECONDS` | `3600` | Timeout mỗi lần FFmpeg |

Mã lỗi: `MISSING_HOOK`, `MISSING_REVIEW`, `FFMPEG_MISSING`, `FFPROBE_MISSING`, `CONCAT_FAILURE`, `CODEC_MISMATCH`, `INVALID_OUTPUT`, `DISK_FULL`, `COMPOSER_TIMEOUT`; hủy pipeline dùng `JOB_CANCELLED`.

## Smoke test

```powershell
.\.venv\Scripts\python.exe scripts\smoke_composer.py "workspace\<job_id>"
```

Sau đó mở `workspace/<job_id>/final/final_video.mp4` hoặc xem preview final trên frontend.
