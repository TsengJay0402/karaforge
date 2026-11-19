# Docker 包裝的 ffmpeg(沒有 root 權限時的替代方案)

KaraForge 需要含 libass 的 `ffmpeg` 與 `ffprobe`。一般情況直接安裝系統套件即可;
如果你在一台不能安裝系統套件、但可以使用 Docker 的機器上(例如共用伺服器),可以用這裡的包裝程式:

```bash
docker build -t karaforge-ffmpeg:trixie docker/ffmpeg-wrapper

# KARAFORGE_HOME 預設是 ~/.local/share/karaforge(Linux)
mkdir -p ~/.local/share/karaforge/bin
ln -s "$PWD/docker/ffmpeg-wrapper/kf-ffmpeg-docker" ~/.local/share/karaforge/bin/ffmpeg
ln -s "$PWD/docker/ffmpeg-wrapper/kf-ffmpeg-docker" ~/.local/share/karaforge/bin/ffprobe

kf doctor   # 應該會顯示 ffmpeg 與 libass 都可用
```

運作方式:

- 映像只有 Debian trixie 加上官方套件庫的 `ffmpeg`(7.1,含 libass、libx264)。
- 包裝程式依照被呼叫時的檔名決定要執行 `ffmpeg` 還是 `ffprobe`,然後 `docker run`:
  目前工作目錄與指令列裡每個絕對路徑所在的目錄,都會以**相同路徑**掛載進容器,所以不需要轉換路徑。
- 容器沒有網路(`--network none`)、以你自己的 uid/gid 執行、結束後自動刪除(`--rm`)。
- 收到 SIGTERM／SIGINT 時 Docker 會轉送給容器內的 ffmpeg,所以 KaraForge 的「取消」功能可以正常運作。

限制:

- 每次呼叫多出約 0.3 秒的容器啟動時間。
- 符號連結如果指向沒有掛載的目錄,在容器內會失效。KaraForge 自己只使用實體檔案或硬連結。
- 硬體編碼(NVENC／VAAPI／QSV)需要另外把裝置傳進容器,這個包裝程式沒有處理。

環境變數:

| 變數 | 說明 |
|---|---|
| `KARAFORGE_FFMPEG_IMAGE` | 要執行的映像,預設 `karaforge-ffmpeg:trixie` |
| `KARAFORGE_FFMPEG_MOUNTS` | 額外要掛載的目錄,以 `:` 分隔 |
