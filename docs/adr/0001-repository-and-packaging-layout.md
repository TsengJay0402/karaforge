# ADR 0001：儲存庫與套件結構

- 狀態：已採用
- 日期：2026-11-19

## 背景

規格建議的儲存庫結構把引擎放在 `engine/karaforge/`、評測放在 `bench/`、另外有 `fonts/`、`themes/`、`web/`。
需要決定：有幾個 Python 發佈套件、評測程式怎麼被 `kf bench` 找到、字型／主題／前端建置結果怎麼跟著套件走。

## 選項

1. **uv workspace，兩個發佈套件**（`karaforge`、`karaforge-bench`）。界線清楚，但 `kf bench` 需要跨套件的
   選用相依，安裝與版本要同步兩份 `pyproject.toml`。
2. **單一發佈套件，兩個 import 套件**：`engine/karaforge` → `karaforge`、`bench/kfbench` → `kfbench`，
   由同一個 `pyproject.toml`（hatchling）打包。
3. 把評測放進 `karaforge.bench` 子套件。最簡單，但偏離規格的頂層 `bench/`。

## 決定

採用選項 2。

- 根目錄只有一個 `pyproject.toml`；`[tool.hatch.build.targets.wheel].packages` 指向 `engine/karaforge` 與
  `bench/kfbench`。
- `fonts/`、`themes/` 以 `force-include` 打包到 `karaforge/_bundled/`；執行時 `karaforge.paths.bundled_dir()`
  先找套件內的副本，找不到再回到原始碼樹（editable 安裝、開發時）。前端的 `web/dist` 用同一個機制，
  另外可用 `KARAFORGE_WEB_DIST` 覆寫。
- 評測的 import 名稱用 `kfbench` 而不是 `bench`，避免安裝後佔用太通用的頂層名稱；
  規格裡的 `bench/synth/` 對應到 `bench/kfbench/synth/`，`bench/real/` 仍是放使用者自備資料的目錄。
- 測試統一放在頂層 `tests/`（`unit/`、`integration/`、`visual/`），前端測試在 `web/`。

## 後果

- 使用者只需要 `uv sync`（或 `pip install karaforge`）一個動作，`kf bench` 就可用。
- wheel 會包含評測程式，體積略增（純 Python，影響很小）。
- 要發佈 wheel 時必須先建置前端；Docker 映像以多階段建置處理，並用 `KARAFORGE_WEB_DIST` 指向建置結果。
