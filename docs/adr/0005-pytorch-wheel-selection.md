# ADR 0005：PyTorch 的安裝來源（CPU／CUDA）

- 狀態：已採用（CUDA 路徑未能在開發環境實測）
- 日期：2026-11-20

## 背景

PyTorch 在 PyPI 上的 Linux wheel 內含 CUDA 執行庫（數 GB）；只用 CPU 的機器、CI 與 `cpu` Docker 映像
應該用 `download.pytorch.org/whl/cpu` 的小型 wheel。規格希望「`uv sync` 之後即可 `kf serve`」，
同時要有 `cpu` 與 `cuda` 兩種映像，並且「有 CUDA 時自動加速」。

## 決定

- `torch` 是一般相依：**不加任何 extra 的 `uv sync` 就能用**，取得 PyPI 預設的 wheel
  （Linux 上含 CUDA、macOS 上含 MPS）。有 NVIDIA 顯示卡的 Linux 使用者不需要多做任何事。
- `--extra cpu`：改從 PyTorch 的 CPU 索引安裝，體積小很多。CI、`cpu` 映像與沒有顯示卡的機器使用。
- `--extra cuda`：固定使用 CUDA 12.6 的索引（Windows 加 NVIDIA 需要；也讓 CTranslate2 所需的
  cuDNN 9／cuBLAS 12 版本與 PyTorch 帶的一致）。
- 兩個 extra 互斥（`[tool.uv] conflicts`），`uv.lock` 同時鎖住三種組合。
- `torchvision` 只是 `audio-separator` 的間接相依，但必須跟 `torch` 來自同一個索引，所以也列在兩個 extra 裡。
- 鎖檔時用 `constraint-dependencies` 把 `torch` 壓在 2.15 以下：2.15.0 發佈時 PyTorch 索引上還沒有對應的
  `torchvision`。這個限制只影響鎖檔，不寫進套件的發佈資訊。
- 執行時的裝置選擇在 `karaforge.device.resolve_device()`：`auto` 依序嘗試 CUDA、MPS、CPU；
  明確指定但不可用時退回 CPU 並附上原因（給 CLI／UI 顯示）。`KARAFORGE_DEVICE` 可以覆寫 `auto`。

## 後果

- 在這個開發環境一律使用 `uv sync --extra cpu --group bench`；`uv run` 會依預設組合重新同步，
  所以本專案的指令都直接呼叫 `.venv/bin/...` 或 `uv run --no-sync`（Makefile 與 CI 也是）。
- ONNX Runtime 只裝 CPU 版：GPU 上的分離改用 PyTorch 原生的模型（`audio-separator` 對 MDX 模型也能走 PyTorch），
  避免 `onnxruntime` 與 `onnxruntime-gpu` 互相覆蓋。
- **CUDA、MPS 的實際執行沒有驗證過**（開發主機沒有 GPU），列在 REPORT.md 的未驗證清單。
