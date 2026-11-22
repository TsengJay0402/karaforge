# 授權清單

KaraForge 本身以 **Apache License 2.0** 釋出（見根目錄的 `LICENSE`）。
這份文件列出它依賴或會下載的東西各自的授權。清單裡的授權名稱取自各套件安裝後的中繼資料（Python 的 `METADATA`、npm 的 `package.json`）
與模型發布頁面，日期是 2026-11-21；**不是法律意見**，要做商業用途請自行查證。

重點先講：

- **你放進來的歌曲、影片與歌詞的權利，不在這份清單的範圍內。** 把有著作權的歌曲做成卡拉 OK 影片並散布，通常需要權利人的授權。
  KaraForge 只是工具，請自行確認你有權使用素材。
- **模型權重不隨程式散布**，是使用者執行 `kf models download`（或第一次處理時）才從原始出處下載的。
- 預設會用到的模型都允許商業使用。唯一不允許的 `mms-fa`（CC-BY-NC-4.0）不在任何預設組合裡，必須明確加上 `--accept-license` 才會下載。
- 以 `uv sync` 安裝的執行環境（預設安裝，以及選用的 `qwen` extra）沒有 GPL 或非商業授權的 Python 套件。
  原本會被間接帶進來的三個——`diffq`（CC-BY-NC）、`soynlp`（GPLv3）與前端的 `rvfc-polyfill`（GPLv3）——KaraForge 都用不到，已經排除（見下方）。
  只有開發時才用的評測工具會安裝 GPL 套件。
- 瀏覽器預覽用的 JASSUB（libass 的 WebAssembly 版）是 **LGPL**；它以獨立、可替換的檔案形式隨前端提供，詳見下方說明。
- ffmpeg 不隨 KaraForge 散布（由使用者安裝，或由 Docker 映像從 Debian 套件庫安裝）。
- 選用的 yt-dlp 也不隨 KaraForge 散布，由使用者自行安裝（Docker 映像也不包含）。

## 模型（使用者自行下載）

`kf models list` 會列出同一份資訊；不允許商業使用的以黃色標示。

| 模型 id | 用途 | 授權 | 可商用 | 來源 |
|---|---|---|---|---|
| `whisper-tiny`／`base`／`small`／`medium` | 語音辨識 | MIT | 是 | [Systran/faster-whisper-*](https://huggingface.co/Systran)（OpenAI Whisper 的 CTranslate2 轉檔） |
| `whisper-large-v3-turbo` | 語音辨識 | MIT | 是 | [mobiuslabsgmbh/faster-whisper-large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) |
| `wav2vec2-zh` | 中文強制對齊（`ctc`） | Apache-2.0 | 是 | [jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn) |
| `wav2vec2-en` | 英文強制對齊（`ctc`） | Apache-2.0 | 是 | [facebook/wav2vec2-base-960h](https://huggingface.co/facebook/wav2vec2-base-960h) |
| `qwen3-forced-aligner` | 強制對齊（`qwen`、`hybrid`，選用） | Apache-2.0 | 是 | [Qwen/Qwen3-ForcedAligner-0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B) |
| `uvr-mdxnet-kara-2` | 人聲分離 | MIT | 是 | [Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui)；請依 UVR 的要求標示出處 |
| `uvr-metadata` | 分離模型的參數對照表 | MIT | 是 | [TRvlvr/application_data](https://github.com/TRvlvr/application_data) |
| `mms-fa` | 多語強制對齊（`ctc-mms`，選用） | **CC-BY-NC-4.0** | **否** | [MahmoudAshraf/mms-300m-1130-forced-aligner](https://huggingface.co/MahmoudAshraf/mms-300m-1130-forced-aligner)（Meta MMS） |

每個模型在註冊表（`engine/karaforge/models/registry.json`）裡都釘住了確切的版本（commit）與每個檔案的 SHA-256；下載後會驗證。

## 字型（隨程式散布）

三套都是 **SIL Open Font License 1.1**，授權全文在 `fonts/licenses/`。OFL 允許嵌入影片與隨軟體散布。

| 字型 | 檔案 | 來源 |
|---|---|---|
| 源泉圓體 GenSenRounded2 TW B | `fonts/GenSenRounded2TW-B.otf` | ButTaiwan/gensen-font |
| Noto Sans TC Bold | `fonts/NotoSansTC-Bold.otf` | Google／Adobe Noto CJK |
| jf open 粉圓 2.1 | `fonts/jf-openhuninn-2.1.ttf` | justfont/open-huninn-font |

## Python 套件（執行時）

| 套件 | 授權 |
|---|---|
| numpy | BSD-3-Clause（另含 0BSD、MIT、Zlib、CC0 的部分） |
| scipy、soundfile、httpx、uvicorn、torchvision | BSD |
| librosa | ISC |
| pydantic、pyyaml、rich、typer、platformdirs、pypinyin、rapidfuzz、fonttools、faster-whisper、audio-separator、audioread、fastapi | MIT |
| ctranslate2、onnxruntime（由上面的套件帶入） | MIT |
| torch | BSD-3-Clause 為主（中繼資料列為 Apache-2.0、BSD、MIT、BSL-1.0 等的組合） |
| transformers、opencc-python-reimplemented、uharfbuzz、python-multipart | Apache-2.0 |
| qwen-asr（選用，`--extra qwen`） | Apache-2.0（它的相依 `soynlp` 是 GPLv3，已排除，見下方） |

以上都與 Apache-2.0 相容。KaraForge 沒有修改或內嵌其中任何一個的原始碼，只是把它們列為相依套件。

### 刻意排除的間接相依

手寫的清單只會列到想得到的套件。M6 建置 Docker 映像時才發現，核心相依裡藏著一個非商業授權的間接相依；
之後把整個環境掃過一遍，又找到兩個 GPL 的。三個都是「被列為相依，但 KaraForge 走的路徑根本不會載入」的套件，所以直接排除：

| 套件 | 授權 | 誰帶進來的 | 為什麼用不到 | 怎麼確認 |
|---|---|---|---|---|
| `diffq`（Windows 上是 `diffq-fixed`） | CC-BY-NC-4.0 | `audio-separator` | 只有 `audio-separator` 內附的 Demucs 程式碼會載入它；KaraForge 用的是 MDX-Net 模型 | 移除後跑完整條流程與 5 個真實模型的整合測試 |
| `soynlp` | GPL-3.0 | `qwen-asr`（`qwen` extra） | 只有 `qwen-asr` 自己的韓文前處理會載入它；KaraForge 自己做斷詞，不呼叫那個函式 | 移除後以 `gpu-quality`（`hybrid` 對齊器）跑完整條流程；另外直接以韓文歌詞呼叫 Qwen 對齊器 |
| `rvfc-polyfill`（npm） | GPL-3.0 | `jassub` | 它替沒有 `requestVideoFrameCallback` 的瀏覽器補上這個方法，而 JASSUB 只有在跟著 `<video>` 元素播放時才用得到；KaraForge 用的是畫布模式，自己告訴 JASSUB 每個影格的時間 | 排除後 14 個瀏覽器端對端測試（含預覽對匯出的畫面比對）與真實模型的完整流程通過 |

排除的方式：

- Python：`pyproject.toml` 的 `[tool.uv] override-dependencies`。用 `uv sync` 安裝（README 與 Docker 映像的做法）**不會**裝到它們，
  也因此不需要 C 編譯器（`diffq` 沒有預編譯檔）。
- 前端：`web/vite.config.ts` 把 `rvfc-polyfill` 換成一個空的模組，並且在打包結果裡出現它的程式碼時讓建置失敗。
  它仍然會被 `npm ci` 下載到 `node_modules`，但不會進入 `web/dist`，也就不會隨 KaraForge 散布。

**要注意：Python 的排除只對 uv 有效。** 如果改用 `pip install` 安裝相依套件，`diffq` 與 `soynlp` 會被裝進來；
商業使用或再散布之前請自行移除（`pip uninstall diffq soynlp`）。

### 整個環境的掃描

`scripts/scan_licenses.py` 讀取環境裡每一個套件的授權中繼資料（`License`、`License-Expression`、classifier），列出不是寬鬆授權的、
沒有填授權的，以及應該被排除卻裝著的套件；發現這份文件沒有交代的項目時會以錯誤結束。同一個檢查也是單元測試
（`tests/unit/test_dependency_licences.py`），所以新增相依套件時如果帶進這類授權，測試會失敗。2026-11-21 的結果：

| 安裝組合 | 套件數 | 掃描到的非寬鬆授權 |
|---|---:|---|
| 核心（`uv sync --extra cpu`，README 與 Docker 映像的安裝方式） | 114（不含開發工具是 98） | `soxr`：LGPL-2.1-or-later（`librosa` 用它重新取樣；以獨立套件動態載入，沒有修改） |
| 加上選用的 `--extra qwen` | 139 | 同上，沒有其他 |
| 加上評測工具 `--group bench`（只在開發時使用） | 166 | `phonemizer-fork`：**GPLv3+**；`espeakng-loader`：中繼資料沒有填，內含 GPLv3 的 espeak-ng 函式庫；`num2words`：LGPL。三個都是語音合成前處理 `misaki` 的相依 |

前端以同樣的方式看過正式相依（`npm ls --omit=dev --all`，共 18 個套件）：15 個 MIT、1 個 Apache-2.0，加上 `jassub` 與上面已排除的 `rvfc-polyfill`。

評測工具裡的 GPL 套件沒有排除：它們是產生合成測資時真的會用到的（Kokoro 的英文前處理以 espeak-ng 處理字典裡沒有的字），
而且評測工具不是產品的一部分——不在預設安裝裡、不在 Docker 映像裡，只用來產生測資。用 GPL 程式產生的音訊不受 GPL 約束。

這是依中繼資料做的機械式掃描：中繼資料寫錯、沒寫，或是套件裡夾帶了別的授權的程式碼，都掃不到。**不是法律稽核。**

### 只在開發與評測時使用（不是執行時相依）

| 套件 | 授權 | 用途 |
|---|---|---|
| pytest、pytest-cov、ruff、pyright | MIT | 測試、lint、型別檢查 |
| hypothesis | MPL-2.0 | 性質測試 |
| httpx2、scipy-stubs | BSD-3-Clause | 測試用戶端、型別定義 |
| kokoro、misaki | Apache-2.0 | 合成評測資料的語音合成（Kokoro-82M 模型權重亦為 Apache-2.0）；`misaki` 會帶進 GPL 的 espeak-ng 相關套件，見上方的掃描 |
| pyworld | MIT（套件內附授權檔；中繼資料的授權欄位沒有填） | 合成評測資料的聲碼器 |
| en-core-web-sm（spaCy 模型） | MIT | misaki 的英文斷詞 |

## 前端（打包後隨程式散布）

| 套件 | 授權 |
|---|---|
| react、react-dom、react-router-dom、zustand、immer、@tanstack/react-query | MIT |
| **jassub** 2.5.38 | **LGPL-2.1-or-later** AND (FTL OR GPL-2.0-or-later) AND MIT AND MIT-Modern-Variant AND ISC AND NTP AND Zlib AND BSL-1.0 |

`jassub` 相依的 `rvfc-polyfill`（GPL-3.0）不會進入打包結果，見上方「刻意排除的間接相依」。
開發工具（vite、vitest、typescript、eslint、@playwright/test、testing-library…）不隨成品散布；它們的授權沒有逐一掃描。

### 關於 JASSUB 的 LGPL

JASSUB 把 libass、FreeType、HarfBuzz、FriBidi 等函式庫編譯成 WebAssembly，其中 libass 是 ISC、FriBidi 是 LGPL-2.1，
所以整體以 LGPL-2.1-or-later 等授權的組合散布。KaraForge 的用法是：

- 不修改 JASSUB；
- 打包後它是 `web/dist/assets/` 裡**獨立的檔案**（`jassub-*.js`、`jassub-worker-*.js`、`jassub-worker-*.wasm`），透過它公開的 API 使用；
  同一個資料夾裡的 `default-*.woff2` 是 JASSUB 附帶的後備字型（依 JASSUB 的說明是 Liberation Sans，SIL OFL 1.1）；
- 使用者可以用自己編譯的版本替換這些檔案（LGPL 要求的「可替換」）。

依我們的理解，這樣使用符合 LGPL，而且不影響 KaraForge 自己以 Apache-2.0 授權；但這是工程師的理解，不是律師的意見。
如果你要把 KaraForge 的前端整合進不能接受 LGPL 元件的產品，可以把預覽元件（`web/src/editor/Preview.tsx`）換成別的 ASS 算繪器——
其餘的程式碼不依賴 JASSUB。原始碼：<https://github.com/ThaUnknown/jassub>。

## 外部程式

| 程式 | 授權 | 怎麼取得 |
|---|---|---|
| ffmpeg／ffprobe（需含 libass） | LGPL 或 GPL，視編譯選項而定 | 使用者自行安裝；Docker 映像從 Debian 套件庫安裝（屬於「僅是彙集」的獨立程式） |
| yt-dlp（選用：用影片網址建立專案） | Unlicense（公有領域） | 使用者自行安裝；Docker 映像不包含 |

KaraForge 以子行程呼叫 ffmpeg 與 yt-dlp，沒有連結它們的函式庫。

## 測試資料

- `tests/fixtures/songs/` 與評測用的歌曲是**程式合成的**（語音合成 + 聲碼器 + 合成伴奏），歌詞是為這個專案寫的，沒有使用任何有著作權的錄音或歌詞。產生方式見 [benchmark.md](benchmark.md)。
- `tests/fixtures/polyphones/` 的句子是為這個專案寫的。
