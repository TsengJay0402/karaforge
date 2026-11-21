# ADR 0012：相依套件的授權邊界

- 狀態：已採用
- 日期：2026-11-21

## 背景

規格要求所有相依套件與模型的授權都與 Apache-2.0 相容，並列在 `docs/LICENSES.md`。
M0 到 M5 期間，那份清單是手寫的，只涵蓋直接相依與模型。M6 發生了三件事：

1. 建置 Docker 映像失敗，因為 `audio-separator` 的相依 `diffq` 沒有預編譯檔、需要 C 編譯器。查它的時候才看到授權是 **CC-BY-NC-4.0**。
   它從 M1 起就一直裝在開發環境與示範用的安裝流程裡。
2. 因此把整個 Python 環境的授權中繼資料掃了一遍，找到選用的 `qwen` extra 帶進來的 `soynlp`（**GPL-3.0**），
   以及評測工具帶進來的 `phonemizer-fork`（GPL-3.0+）與 `espeakng-loader`（內含 espeak-ng）。
3. 接著以同樣的方式看前端的正式相依，找到 `jassub` 相依的 `rvfc-polyfill`（**GPL-3.0**）——而且它的程式碼確實被打包進 `web/dist`，
   也就是 Docker 映像與 `kf serve` 送出去的檔案裡。

三個問題都在 0.1.0 定版之前處理掉了。但要說清楚：在這之前，開發環境從 M1 起一直裝著 `diffq`，
git 歷史裡這次修正之前的每一個 commit，照它的 lock 檔安裝或打包，也都會含有這些套件。

## 決定

**邊界：KaraForge 預設安裝的、以及它自己散布的東西，不可以含有 GPL、AGPL 或非商業授權的程式。**
具體是指：`uv sync --extra cpu|cuda`（含選用的 `qwen` extra）裝出來的環境、Docker 映像、打包後的前端。

- **用不到的就排除。** `diffq`、`soynlp`、`rvfc-polyfill` 都是「被上游列為相依，但 KaraForge 走的路徑不會載入」。
  Python 用 uv 的 `override-dependencies`（加上一個永遠不成立的條件）排除；前端用 Vite 的 alias 換成空模組，
  並在打包結果出現它的程式碼時讓建置失敗。每一個都在移除後實際跑過會經過那段上游程式的流程。
- **LGPL 可以**，前提是不修改、以可替換的獨立單位使用：`soxr`（Python 套件）、JASSUB（打包後是獨立的檔案）。
- **評測工具不在邊界內。** `--group bench` 是開發用的相依群組，會安裝 GPL 的 espeak-ng 相關套件（透過 Kokoro 的前處理 `misaki`）。
  它們真的被用到，排除會改變已經定稿的合成測資；而評測工具不隨產品安裝或散布。
- **用工具守住，不靠記憶。** `scripts/scan_licenses.py` 掃描目前環境，`tests/unit/test_dependency_licences.py` 在出現沒有交代過的
  GPL／非商業授權套件、或被排除的套件又被裝回來時失敗。

`pyproject.toml` 另外替 `diffq` 與 `diffq-fixed` 寫了 `dependency-metadata`：uv 鎖定相依時連不會安裝的套件也要知道它的中繼資料，
而這兩個只有原始碼發行檔，`diffq-fixed` 的發行檔甚至無法建置（缺少 `setup.py` 要編譯的 `.pyx`），會讓 `uv lock` 直接失敗。

## 考慮過的其他做法

- **拿掉 `qwen` extra。** 最乾淨，但會失去 `hybrid` 對齊器（規格建議的 Qwen3-ForcedAligner；英文與混合歌詞上比預設好）。
  既然 `soynlp` 只在 `qwen-asr` 的韓文前處理裡被延遲載入，排除它就夠了。
- **換掉 `audio-separator`**，自己用 onnxruntime 跑 MDX-Net。可以連帶去掉一大串用不到的相依，但等於重寫分離的前後處理，
  而分離結果會影響所有已定稿的評測數字。列為日後可以做的事。
- **只在文件裡警告**，不排除。對 `diffq` 不可接受：它在預設安裝裡。

## 後果與限制

- **排除只對 uv 有效。** 用 `pip install` 安裝相依套件的人會裝到 `diffq` 與 `soynlp`；文件有寫，但沒有機制擋住。
  專案目前沒有發布到 PyPI；發布之前要先解決這一點（例如把 `audio-separator` 換掉，或說服上游把 `diffq` 改成選用）。
- 上游改版後可能開始在別的路徑載入這些套件。`qwen-asr` 若在 import 時就需要 `soynlp`，Qwen 對齊器會回報缺少套件的錯誤；
  `audio-separator` 若在 MDX 路徑載入 `diffq`，人聲分離會失敗。兩者都會被真實模型的整合測試抓到，但前提是升級後有人跑它們。
- 掃描只看中繼資料：填錯、沒填，或套件裡夾帶其他授權的程式碼，都看不出來。沒有做法律上的稽核。
- 前端的開發工具（不隨成品散布）沒有掃描。
- `rvfc-polyfill` 仍會被 `npm ci` 下載到開發者的 `node_modules`，只是不進入打包結果。
