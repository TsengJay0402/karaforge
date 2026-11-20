# KaraForge 合成測資評測(dev,產生器 v1)

產生時間:2026-11-21 03:48

- karaforge: 0.1.0.dev0
- python: 3.12.3
- machine: x86_64
- cpu: x86_64
- threads: 8
- device: cpu
- commit: 3dd0d6a
- started: 2026-11-21T03:38:41+08:00
- finished: 2026-11-21T03:48:53+08:00

> 分組 `dev`;設定檔 `balanced`;音檔 48 個。

## 與規格 §10.4 目標對照

設定:`balanced`,中文,10 dB(共 272 個 token)

| 指標 | 目標 | 實測 | 結果 |
|---|---:|---:|---|
| 起始時間誤差中位數 (ms) | ≤ 60 | 11.0 | 達成 |
| 起始時間誤差 P95 (ms) | ≤ 250 | 90.9 | 達成 |
| 需人工修正比例(誤差 > 150 ms,%) | ≤ 10 | 2.9 | 達成 |
| 隨機 lock 5% 錨點後的需人工修正比例(%) | ≤ 5 | 2.7 | 達成 |

## 各設定的對齊準確度

### zh,0 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 272 | 18 | 99 | 260 | 6.2% | 0.0% | +10 |
| `balanced / anchors-random-5%` | 259 | 18 | 99 | 307 | 6.9% | 0.0% | +12 |
| `balanced / anchors-lowconf-5%` | 259 | 18 | 118 | 552 | 9.3% | 0.0% | +14 |

### zh,5 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 272 | 13 | 65 | 96 | 3.7% | 0.0% | -3 |
| `balanced / anchors-random-5%` | 259 | 12 | 70 | 101 | 4.2% | 0.0% | -3 |
| `balanced / anchors-lowconf-5%` | 259 | 13 | 59 | 92 | 2.7% | 0.0% | -2 |

### zh,10 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 272 | 11 | 55 | 91 | 2.9% | 0.0% | -4 |
| `balanced / anchors-random-5%` | 259 | 11 | 53 | 83 | 2.7% | 0.0% | -4 |
| `balanced / anchors-lowconf-5%` | 259 | 11 | 54 | 94 | 3.9% | 0.0% | -3 |

### zh,20 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 272 | 8 | 44 | 65 | 2.6% | 0.0% | -2 |
| `balanced / anchors-random-5%` | 259 | 8 | 45 | 74 | 2.7% | 0.0% | -2 |
| `balanced / anchors-lowconf-5%` | 259 | 8 | 44 | 56 | 1.9% | 0.0% | -2 |

### en,0 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 204 | 42 | 151 | 203 | 10.3% | 0.0% | +26 |
| `balanced / anchors-random-5%` | 194 | 42 | 194 | 336 | 12.4% | 0.0% | +27 |
| `balanced / anchors-lowconf-5%` | 194 | 42 | 196 | 533 | 12.9% | 0.0% | +22 |

### en,5 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 204 | 26 | 120 | 172 | 5.9% | 0.0% | -6 |
| `balanced / anchors-random-5%` | 194 | 29 | 125 | 203 | 6.7% | 0.0% | -5 |
| `balanced / anchors-lowconf-5%` | 194 | 24 | 115 | 183 | 5.7% | 0.0% | -6 |

### en,10 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 204 | 17 | 130 | 290 | 8.3% | 2.0% | -7 |
| `balanced / anchors-random-5%` | 194 | 19 | 147 | 598 | 9.8% | 0.0% | -6 |
| `balanced / anchors-lowconf-5%` | 194 | 16 | 122 | 231 | 7.7% | 0.0% | -7 |

### en,20 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 204 | 17 | 145 | 345 | 9.8% | 2.5% | -6 |
| `balanced / anchors-random-5%` | 194 | 15 | 190 | 377 | 11.9% | 0.0% | -6 |
| `balanced / anchors-lowconf-5%` | 194 | 13 | 117 | 170 | 6.2% | 0.0% | -6 |

### mixed,0 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 187 | 38 | 311 | 582 | 13.9% | 0.5% | -4 |
| `balanced / anchors-random-5%` | 177 | 37 | 331 | 629 | 13.6% | 0.6% | +1 |
| `balanced / anchors-lowconf-5%` | 177 | 39 | 378 | 673 | 16.9% | 0.6% | -6 |

### mixed,5 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 187 | 19 | 286 | 748 | 13.9% | 0.5% | -8 |
| `balanced / anchors-random-5%` | 177 | 20 | 573 | 1069 | 15.8% | 0.6% | -7 |
| `balanced / anchors-lowconf-5%` | 177 | 19 | 281 | 674 | 13.0% | 0.0% | -6 |

### mixed,10 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 187 | 14 | 288 | 754 | 15.0% | 0.5% | -8 |
| `balanced / anchors-random-5%` | 177 | 14 | 599 | 873 | 18.6% | 0.0% | -8 |
| `balanced / anchors-lowconf-5%` | 177 | 12 | 132 | 673 | 10.2% | 0.0% | -8 |

### mixed,20 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 187 | 10 | 221 | 460 | 11.8% | 0.5% | -7 |
| `balanced / anchors-random-5%` | 177 | 11 | 285 | 782 | 14.1% | 0.6% | -8 |
| `balanced / anchors-lowconf-5%` | 177 | 10 | 226 | 709 | 11.9% | 0.6% | -7 |

## 結束時間(行尾長音)與信心度

| 設定 | 語言 | SNR | 行尾結束誤差中位數 ms | 行尾結束誤差 P90 ms | 信心度 AUROC | 檢查信心最低 10% 找到的問題比例 | 20% |
|---|---|---:|---:|---:|---:|---:|---:|
| `balanced` | zh | 0 dB | 68 | 393 | 0.88 | 59% | 71% |
| `balanced / anchors-random-5%` | zh | 0 dB | 68 | 303 | 0.91 | 67% | 78% |
| `balanced / anchors-lowconf-5%` | zh | 0 dB | 70 | 308 | 0.96 | 75% | 88% |
| `balanced` | zh | 5 dB | 21 | 146 | 0.95 | 70% | 90% |
| `balanced / anchors-random-5%` | zh | 5 dB | 21 | 146 | 0.97 | 82% | 100% |
| `balanced / anchors-lowconf-5%` | zh | 5 dB | 21 | 178 | 0.99 | 100% | 100% |
| `balanced` | zh | 10 dB | 14 | 132 | 0.95 | 75% | 88% |
| `balanced / anchors-random-5%` | zh | 10 dB | 14 | 82 | 0.94 | 71% | 86% |
| `balanced / anchors-lowconf-5%` | zh | 10 dB | 14 | 82 | 0.99 | 90% | 100% |
| `balanced` | zh | 20 dB | 10 | 22 | 0.99 | 100% | 100% |
| `balanced / anchors-random-5%` | zh | 20 dB | 9 | 23 | 0.99 | 100% | 100% |
| `balanced / anchors-lowconf-5%` | zh | 20 dB | 9 | 18 | 0.99 | 100% | 100% |
| `balanced` | en | 0 dB | 599 | 1444 | 0.84 | 43% | 67% |
| `balanced / anchors-random-5%` | en | 0 dB | 599 | 1462 | 0.83 | 46% | 67% |
| `balanced / anchors-lowconf-5%` | en | 0 dB | 599 | 1932 | 0.87 | 52% | 76% |
| `balanced` | en | 5 dB | 112 | 579 | 0.92 | 58% | 100% |
| `balanced / anchors-random-5%` | en | 5 dB | 193 | 880 | 0.92 | 62% | 77% |
| `balanced / anchors-lowconf-5%` | en | 5 dB | 112 | 1427 | 0.89 | 55% | 91% |
| `balanced` | en | 10 dB | 30 | 384 | 0.96 | 71% | 94% |
| `balanced / anchors-random-5%` | en | 10 dB | 17 | 375 | 0.94 | 63% | 84% |
| `balanced / anchors-lowconf-5%` | en | 10 dB | 16 | 375 | 0.94 | 67% | 93% |
| `balanced` | en | 20 dB | 22 | 235 | 0.96 | 60% | 95% |
| `balanced / anchors-random-5%` | en | 20 dB | 27 | 776 | 0.90 | 43% | 83% |
| `balanced / anchors-lowconf-5%` | en | 20 dB | 21 | 228 | 0.92 | 75% | 83% |
| `balanced` | mixed | 0 dB | 454 | 2129 | 0.75 | 23% | 42% |
| `balanced / anchors-random-5%` | mixed | 0 dB | 590 | 1957 | 0.78 | 25% | 46% |
| `balanced / anchors-lowconf-5%` | mixed | 0 dB | 865 | 2576 | 0.80 | 40% | 53% |
| `balanced` | mixed | 5 dB | 88 | 2102 | 0.79 | 35% | 50% |
| `balanced / anchors-random-5%` | mixed | 5 dB | 141 | 3267 | 0.84 | 43% | 54% |
| `balanced / anchors-lowconf-5%` | mixed | 5 dB | 75 | 1949 | 0.82 | 43% | 57% |
| `balanced` | mixed | 10 dB | 26 | 2100 | 0.79 | 36% | 50% |
| `balanced / anchors-random-5%` | mixed | 10 dB | 312 | 2482 | 0.81 | 30% | 52% |
| `balanced / anchors-lowconf-5%` | mixed | 10 dB | 19 | 2081 | 0.77 | 28% | 50% |
| `balanced` | mixed | 20 dB | 12 | 1186 | 0.79 | 36% | 64% |
| `balanced / anchors-random-5%` | mixed | 20 dB | 12 | 2281 | 0.80 | 40% | 60% |
| `balanced / anchors-lowconf-5%` | mixed | 20 dB | 11 | 1180 | 0.81 | 52% | 67% |

## 處理時間(每分鐘音訊所需秒數,CPU)

| 設定 | ingest | separate | analyze | asr | align | 合計 | 即時倍率 |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 2.0 | 37.6 | 0.5 | 18.2 | 11.1 | 69.4 | 0.9x |
| `balanced / anchors-random-5%` | 2.0 | 37.6 | 0.5 | 18.2 | 0.1 | 58.4 | 1.0x |
| `balanced / anchors-lowconf-5%` | 2.0 | 37.6 | 0.5 | 18.2 | 0.1 | 58.4 | 1.0x |

時間是各階段「實際計算」時記錄下來的秒數;同一首歌的後續設定會沿用分離與辨識的快取,但表中仍列出該階段原本的計算時間。

