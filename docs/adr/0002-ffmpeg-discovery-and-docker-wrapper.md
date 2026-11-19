# ADR 0002：ffmpeg 的尋找順序與 Docker 包裝

- 狀態：已採用
- 日期：2026-11-19

## 背景

KaraForge 把 ffmpeg／ffprobe 當成外部程式呼叫（不連結、不隨套件散佈，避免把 GPL 元件併入 Apache-2.0 的發佈物）。
開發機沒有安裝 ffmpeg，而我不想為了這個專案用 sudo 安裝系統套件；下載第三方靜態執行檔來跑的做法
在這個環境被權限機制擋下（見 `docs/ENVIRONMENT.md`）。

## 選項

1. 只支援 `PATH` 上的 ffmpeg。
2. 把 ffmpeg 執行檔打包進 Python 套件（例如依賴 `imageio-ffmpeg`）。沒有 ffprobe，而且會把 GPL 執行檔變成預設相依。
3. 可設定的尋找順序，加上一個「用 Docker 跑 Debian 官方 ffmpeg」的包裝程式給沒有 root 的使用者。

## 決定

採用選項 3。

- 尋找順序：`KARAFORGE_FFMPEG`／`KARAFORGE_FFPROBE` → `PATH` → `$KARAFORGE_HOME/bin/`。
- `docker/ffmpeg-wrapper/` 提供映像與包裝程式；包裝程式把指令列中的絕對路徑所在目錄以相同路徑掛載，
  容器無網路、以呼叫者身分執行。
- 引擎呼叫 ffmpeg 時一律：加上 `-nostdin`、把工作目錄設在專案內的暫存目錄、濾鏡字串只用相對檔名
  （同時避開 ffmpeg 濾鏡語法的跳脫問題），取消時送 SIGTERM。這些規則讓原生與包裝兩種 ffmpeg 行為一致。
- `kf doctor` 檢查 ffmpeg 是否存在、是否含 libass 與需要的編碼器。

## 後果

- 沒有 root 的機器也能完整運作，代價是每次呼叫約 0.3 秒的容器啟動時間。
- 引擎不能假設暫存檔在系統的 `/tmp`；所有中間檔都放在專案資料夾的 `cache/` 之下（這對可重現性也比較好）。
- 測試使用 repo 內的 `.pytest_tmp/` 作為需要 ffmpeg 的測試的工作目錄。
