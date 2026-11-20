# 主題（Theme YAML）

主題決定歌詞長什麼樣子、放在哪裡、什麼時候出現。它是一個 YAML 檔；**同一個主題同時用於瀏覽器預覽與匯出**，所以看到的就是輸出的結果。

## 內建主題

| 名稱 | 說明 |
|---|---|
| `classic-ktv` | 經典 KTV：白字黑框，唱過的字變成演唱者的顏色並換成白框；男藍、女粉、合唱綠。預設主題。 |
| `clean-center` | 簡潔置中：Noto Sans 黑體、細框、沒有陰影，兩排都置中，唱過的字變成暖黃色。適合歌詞影片或詩歌投影。 |
| `pop-round` | 粉圓流行：jf open 粉圓字型、粗白框與粉彩填色；合唱行上半男色、下半女色。 |
| `zhuyin-learner` | 注音學習：每個字上方顯示讀音，字距與行距加大。 |

內建主題在原始碼的 `themes/` 資料夾。

## 使用與自訂

- 專案用哪個主題記在 `project.json` 的 `style.theme`。
- **只想調整這一首歌**：不必另存主題。在 Web 編輯器的主題面板改，或直接寫進 `style.overrides`，鍵是下面欄位的點號路徑：

  ```json
  "style": { "theme": "classic-ktv", "overrides": { "font.size": 96, "ruby.enabled": true, "layout.rows.0.y": 0.7 } }
  ```

- **想重複使用**：在主題面板「另存成新主題」，或把 YAML 檔放進使用者主題資料夾
  `$KARAFORGE_HOME/themes/`（預設 `~/.local/share/karaforge/themes/`）。主題是用**檔名**（不含 `.yaml`）來指定的，
  檔案裡的 `name` 可以省略；從 Web 另存時，名稱只能用小寫英文、數字與連字號。使用者主題與內建主題同名時，以使用者的為準。
- 寫錯欄位名稱或數值超出範圍時，會得到指出是哪個欄位的錯誤訊息；不認得的欄位不會被默默忽略。

## 單位

- **長度**（字級、外框、間距…）是「在 `reference_height`（預設 1080）高的畫面上的像素」。輸出成 720p 或 4K 時會等比例縮放，所以同一個主題在任何解析度下看起來一樣。
- **位置**（`y`、`margin`、`max_width`）是畫面寬或高的比例，0 到 1。
- **時間**是毫秒。
- **顏色**是 `#RRGGBB` 或 `#RRGGBBAA`（AA 是不透明度，`FF` 完全不透明）。

## 完整欄位

以下是 `classic-ktv` 的內容，也就是所有欄位的預設值（`letter_spacing` 的預設是 0，新增的 `layout.paragraph_gap_ms` 預設 2000）：

```yaml
format: 1                     # 主題格式版本
name: classic-ktv             # 必填；要與檔名相同
title: 經典 KTV               # 顯示在選單裡的名稱
description: …
reference_height: 1080

font:
  family: GenSenRounded2 TW B # 字型的 family 名稱（見下方「字型」）
  fallback: Noto Sans TC      # 主要字型缺字時使用
  size: 84                    # 一個中文字的高度
  letter_spacing: 2

text:
  outline: 6                  # 外框粗細
  shadow: 3                   # 陰影位移；0 = 沒有陰影
  blur: 0                     # 邊緣柔化

colors:
  unsung: { fill: "#FFFFFF", outline: "#101010" }   # 還沒唱到的字
  shadow: "#000000A0"
  slots:                      # 唱過之後的顏色；演唱者的 theme_slot 決定用哪一組
    male:   { fill: "#2F7BFF", outline: "#FFFFFF" }
    female: { fill: "#FF4F9A", outline: "#FFFFFF" }
    duet:   { fill: "#35D05B", outline: "#FFFFFF" }
  duet_mode: third            # third：合唱用 duet 這一組；dual：上半男色、下半女色

layout:
  rows:                       # 1 到 4 排；歌詞依序輪流使用
    - { y: 0.74, align: left,  margin: 0.06 }   # y 是這一排的垂直中心
    - { y: 0.88, align: right, margin: 0.06 }   # align: left / center / right
  max_width: 0.86             # 一排最寬佔畫面多少；超過就拆成兩個顯示行
  lead_in_ms: 1500            # 一行至少在開唱前這麼久就出現（那一排空著的話）
  first_lead_in_ms: 3500      # 長停頓後第一行的提前量
  swap_delay_ms: 350          # 另一排開唱後多久，把唱完的這一行換成下一句
  linger_ms: 700              # 最後一行唱完後停留多久
  fade_ms: 150                # 淡入淡出
  section_gap_ms: 4000        # 停頓這麼久就清空畫面、從第一排重新開始
  paragraph_gap_ms: 2000      # 歌詞換段（空行）時，停頓這麼久就夠了；每行都空一行的歌詞不算有分段

ruby:                         # 字上方的讀音（注音／拼音），見 ruby.md
  enabled: false
  scale: 0.4                  # 相對於歌詞字級
  gap: 2                      # 讀音與字之間的距離
  min_spacing: 6              # 相鄰讀音之間至少留多少；不夠時把字推開

countdown:                    # 長停頓後開唱前的倒數圓點
  enabled: true
  min_gap_ms: 4000            # 停頓多久才顯示
  dots: 3
  use_beats: true             # 有偵測到速度時，每一拍消失一個
  interval_ms: 1000           # 沒有速度資訊時的間隔
  radius: 13
  spacing: 16
  offset: 18                  # 圓點與歌詞頂端的距離
  fill: "#FFE14D"
  outline: "#202020"

title_card:                   # 第一句之前的歌名、歌手、作詞、作曲
  enabled: true
  y: 0.4
  title_size: 110
  info_size: 52
  line_gap: 26
  max_duration_ms: 6000       # 最多顯示多久（會在第一句出現前結束）
  min_duration_ms: 1500       # 時間不夠這麼久就不顯示
  fill: "#FFFFFF"
  outline: "#101010"
  accent: "#FFE14D"

background:                   # 專案沒有指定背景時使用
  color: "#12141C"
  dim_bottom: 0.45            # 歌詞下方的漸層加暗；0 = 不加，1 = 底邊全黑
```

## 填色是怎麼做的

「唱過的字連外框一起變色」是 KTV 字幕的特徵，ASS 內建的卡拉 OK 標記（`\k`、`\kf`）做不到（它們不會填外框）。
KaraForge 的做法是把同一行畫兩次：下層是「未唱」樣式的整行，上層是「已唱」樣式的同一行，
再用一個由左往右推進的裁切矩形（`\clip` 加上串接的 `\t`）控制上層露出多少。每個字的時間內線性推進，所以長音會慢慢填、快歌會快速掃過。

## 字型

- 內建三套開放授權字型（SIL OFL）：**源泉圓體 GenSenRounded2 TW B**、**Noto Sans TC Bold**、**jf open 粉圓 2.1**。
- `font.family` 寫的是字型的 family 名稱。可用的清單：`kf doctor` 會列出，Web 主題面板的下拉選單也是。
- 字寬是用真實字型（HarfBuzz）量出來的，所以斷行與填色位置和畫面上完全一致。
- 主要字型沒有的字會明確改用 `fallback` 字型；兩者都沒有的字會在處理時報告，而不是畫成方框後默默過關。
- 匯出 MKV 時，字幕用到的字型會一併嵌入檔案。
- 想用自己的字型：把字型檔放進 `$KARAFORGE_HOME/fonts/`，再把主題的 `font.family` 改成它的 family 名稱。
  這條路徑有實作，但自動化測試只涵蓋內建的三套字型。請自行確認字型授權允許嵌入與散布。
