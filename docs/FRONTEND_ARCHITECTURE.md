# Kiến trúc frontend

## Công nghệ

Frontend dùng React, TypeScript, Vite, Vitest, Testing Library và CSS thuần. Production chạy trong trình duyệt và được FastAPI phục vụ. Không cần Electron/Tauri cho chế độ LAN.

## Cấu trúc màn hình

App có sidebar gọn, thanh trạng thái và workspace chính:

1. Màn hình đăng nhập nội bộ.
2. Form YouTube URL và kiểm tra dữ liệu.
3. Preview nguồn.
4. Tiến độ pipeline chín stage.
5. Card trạng thái Hook Engine và Review Engine.
6. Preview/download output hoàn tất.
7. Trang Công việc hiển thị queue và job gần đây dùng chung.

## Cây component

```text
App
`-- AppShell
    |-- Login
    |-- Create video form
    |-- SourcePreview
    |-- PipelineProgress
    |-- EngineCards
    |-- FinalOutput
    `-- Shared Jobs
```

`App` giữ navigation, URL, metadata nguồn, trạng thái kết nối và job đang xem. `useVideoJob` quản lý polling và action. Component trình bày chỉ nhận typed props, không chứa timer mock.

## State

React giữ trang hiện tại, URL/validation, source metadata, active `VideoJob`, readiness, session và thông báo tạm. Job dùng trạng thái backend; danh sách job được polling nên vẫn còn sau reload trình duyệt hoặc restart backend.

## Hợp đồng PipelineClient

`PipelineClient` che giấu transport khỏi UI. Các hàm chính gồm kiểm tra nguồn, tạo/đọc/liệt kê/hủy/retry job, đăng nhập/đăng xuất, readiness và URL asset. UI không import engine, gọi Python, chạy FFmpeg hoặc liên hệ YouTube trực tiếp.

## Mock và backend

Development mặc định dùng `MockPipelineClient` để test UI xác định. Fixture lỗi:

```text
https://youtu.be/mock-video?fixture=fail
```

Production luôn chọn `BackendPipelineClient`; tree-shaking loại mock khỏi bundle. Request dùng credentials và `/api` tương đối. Engine detail nằm sau orchestrator; component và type frontend không import submodule.
