# 開發環境偵測結果

> 偵測時間：2026-11-19。這份文件記錄 KaraForge 開發與驗證所用的機器，
> 目的是讓 `REPORT.md` 裡「實際執行過／未能執行」的驗證清單有憑有據。
> 完成後可用 `kf doctor` 重新產生同類資訊。

## 摘要

| 項目 | 結果 | 對開發的影響 |
|---|---|---|
| 作業系統 | Ubuntu 24.04.5 LTS，Linux 7.0.0-42-generic，x86_64 | 主要開發與驗證平台；macOS／Windows **未驗證** |
| CPU | Intel Core i5-10500 @ 3.10GHz，6 核 12 緒，AVX2／FMA（無 AVX-512） | 所有效能數據都是這顆 CPU 的結果 |
| RAM | 125 GiB | 足夠；跑模型時仍限制執行緒數，避免佔滿整台電腦 |
| 磁碟 | `/` 468 GB，可用 386 GB | 足夠放模型與測資 |
| GPU／CUDA | **無**（沒有 `nvidia-smi`，沒有 NVIDIA 裝置） | CUDA 路徑**無法實測**，只能做程式碼層級的檢查 |
| Apple MPS | 不適用（Linux） | MPS 路徑**無法實測** |
| Intel iGPU | `/dev/dri/renderD128` 存在，但目前帳號不在 `render` 群組 | VAAPI／QSV 硬體編碼**無法實測** |
| Python | 系統 Python 3.12.3（`/usr/bin/python3`），有 `venv` 與 pip 24.0 | 專案以 3.12 開發，宣告支援 3.11+ |
| uv | 原本沒有 → 以官方安裝腳本裝到 `~/.local/bin/uv`（0.13.9），未修改 shell 設定檔 | 依規格使用 uv |
| Node.js | v26.13.1、npm 11.20.0（`~/.local/bin`） | 前端建置與測試可執行 |
| 編譯工具 | gcc／g++ 13.3.0、make；沒有 cmake | 需要編譯的 Python 套件大多可裝 |
| ffmpeg（系統） | **沒有安裝** | 見下方「ffmpeg 的處理方式」 |
| ffmpeg（實際使用） | 7.1.5（Debian trixie 套件，跑在 Docker 容器內），含 libass 0.17.3、libx264、原生 AAC、HarfBuzz 10.2、FreeType 2.13.3 | 匯出與視覺測試都用這一份 |
| Docker | Engine 29.9.3、buildx 0.38.1、compose 5.7.0；目前帳號在 `docker` 群組，daemon 可用 | Docker 映像**可以實際建置與執行** |
| Playwright 瀏覽器 | `~/.cache/ms-playwright` 已有 chromium-1254 與 headless shell；Chromium 所需系統函式庫齊全 | 端對端測試可執行 |
| 系統 CJK 字型 | 有 Noto Sans CJK | 不依賴系統字型；專案自帶 OFL 字型並用 `fontsdir` 指定 |
| sudo | 不使用 | 所有工具都裝在使用者目錄或 Docker 裡，不做系統層級變更 |

## 網路連線（各自實測）

| 目標 | 結果 |
|---|---|
| PyPI（`pypi.org/simple`） | 可連線（HTTP 200，約 0.5 s） |
| npm registry（`registry.npmjs.org`） | 可連線（HTTP 200，首次約 4.8 s） |
| Hugging Face（API 與檔案下載） | 可連線（HTTP 200，約 0.5 s） |
| GitHub（網頁、raw、releases） | 可連線 |
| PyTorch wheel index（`download.pytorch.org`） | 可連線 |
| Docker Hub（`registry-1.docker.io`） | 可連線（未登入回 401 屬正常），實際拉取 `debian:trixie-slim` 成功 |

沒有設定 proxy；pip 與 npm 都使用官方來源。

## ffmpeg 的處理方式

主機沒有 ffmpeg，而專案幾乎每個階段都需要它（ingest、匯出、視覺迴歸測試）。

1. **第一個做法（未採用）**：下載 BtbN 的靜態 ffmpeg 8.1 放進專案內的 `.tools/`。
   壓縮檔已下載，但解壓並執行這個外部執行檔的動作被 Claude Code 的權限分類器擋下，
   因此**沒有解壓、沒有執行**。壓縮檔原本留在 `.tools/ffmpeg-dl/`（被 git 忽略），已在 2026-11-21 收尾時刪除。
2. **第二個做法（未採用）**：`sudo apt install ffmpeg`。我不想為了這個專案改動系統。
3. **實際採用**：用 Debian 官方套件在 Docker 映像裡安裝 ffmpeg，再用一支小包裝程式把
   `ffmpeg`／`ffprobe` 轉成 `docker run`：
   - 映像：`docker/ffmpeg-wrapper/Dockerfile`（`debian:trixie-slim` + `apt install ffmpeg`），本機標籤 `karaforge-ffmpeg:trixie`。
   - 包裝程式：`docker/ffmpeg-wrapper/kf-ffmpeg-docker`，以符號連結放在
     `~/.local/share/karaforge/bin/ffmpeg` 與 `.../ffprobe`（也就是預設 `KARAFORGE_HOME` 的 `bin/`）。
   - 容器以目前使用者身分執行、沒有網路、把指令列出現的絕對路徑所在目錄原樣掛載進去，
     所以引擎不需要做路徑轉換。
   - 每次呼叫多出約 0.3 秒的容器啟動時間；**所有 ffmpeg 相關的效能數字都包含這個額外成本**。

KaraForge 尋找 ffmpeg 的順序是：環境變數 `KARAFORGE_FFMPEG`／`KARAFORGE_FFPROBE` →
`PATH` → `$KARAFORGE_HOME/bin/`。一般使用者裝了系統 ffmpeg 就會直接用系統的，
包裝程式只是「沒有 root 權限時」的替代方案（文件見 `docker/ffmpeg-wrapper/README.md`）。

## 其他與環境有關的決定

- **連接埠**：`kf serve` 的預設連接埠依規格是 8765，但這台主機的 8765 已經被別的程式佔用。
  產品預設值不變；本機的測試與手動驗證一律改用其他連接埠（測試使用系統配置的空閒埠）。
- **執行緒數**：模型推論與評測預設限制在 8 個執行緒以內，讓電腦在跑評測時還能做別的事。
- **Docker 使用範圍**：只建立／刪除名稱以 `karaforge` 開頭的映像與本專案啟動的容器，
  不執行 `docker system prune` 之類會清掉其他專案資料的全域清理。
- **模型與工具存放位置**：使用預設的 `KARAFORGE_HOME`（`~/.local/share/karaforge`）。
- **git**：作者資訊只在 repo 層級設定，未動全域設定；
  開發期間只在本機 commit；公開前改寫過一次歷史（見 REPORT.md 第 7 節「關於 commit 編號」）。

## 因為環境而無法實測的項目（會如實列入 REPORT.md）

- CUDA 推論與 `cuda` Docker 映像的 GPU 執行
- Apple MPS
- NVENC／VAAPI／QSV／VideoToolbox 硬體編碼
- macOS、Windows 上的安裝與執行
- GitHub Actions 的實際執行（本機沒有對應的遠端 repo；CI 的每個步驟會在本機逐一手動執行驗證）
