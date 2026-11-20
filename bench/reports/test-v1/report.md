# KaraForge 合成測資評測(test,產生器 v1)

產生時間:2026-11-21 03:35

- karaforge: 0.1.0.dev0
- python: 3.12.3
- machine: x86_64
- cpu: x86_64
- threads: 8
- device: cpu
- commit: 376ecb5

> 分組 `test`;設定檔 `balanced`;音檔 120 個。

## 與規格 §10.4 目標對照

設定:`balanced`,中文,10 dB(共 747 個 token)

| 指標 | 目標 | 實測 | 結果 |
|---|---:|---:|---|
| 起始時間誤差中位數 (ms) | ≤ 60 | 11.0 | 達成 |
| 起始時間誤差 P95 (ms) | ≤ 250 | 86.0 | 達成 |
| 需人工修正比例(誤差 > 150 ms,%) | ≤ 10 | 2.8 | 達成 |
| 隨機 lock 5% 錨點後的需人工修正比例(%) | ≤ 5 | 4.2 | 達成 |

## 各設定的對齊準確度

### zh,0 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 747 | 20 | 93 | 266 | 7.0% | 0.1% | +17 |
| `balanced / no-coarse(regions)` | 747 | 40 | 3233 | 4940 | 28.5% | 10.3% | +18 |
| `balanced / no-coarse(global)` | 747 | 20 | 98 | 296 | 7.6% | 0.3% | +17 |
| `balanced / no-onset-snap` | 747 | 35 | 98 | 179 | 6.2% | 0.1% | +34 |
| `balanced / no-weak-rescue` | 747 | 20 | 98 | 213 | 6.6% | 0.1% | +17 |
| `balanced / no-long-note` | 747 | 20 | 93 | 266 | 7.0% | 0.1% | +17 |
| `balanced / anchors-random-5%` | 711 | 20 | 94 | 241 | 6.9% | 0.1% | +16 |
| `balanced / anchors-lowconf-5%` | 711 | 20 | 86 | 128 | 4.2% | 0.0% | +16 |
| `balanced+whisper-attn` | 747 | 50 | 222 | 325 | 17.8% | 1.3% | +16 |
| `balanced+ctc-mms` | 747 | 18 | 86 | 161 | 5.2% | 0.0% | +14 |
| `balanced+qwen` | 747 | 20 | 262 | 533 | 13.0% | 0.1% | +16 |
| `balanced+hybrid` | 747 | 20 | 91 | 218 | 6.3% | 0.1% | +17 |

### zh,5 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 747 | 13 | 66 | 106 | 3.7% | 0.0% | -3 |
| `balanced / no-coarse(regions)` | 747 | 18 | 1339 | 3217 | 21.0% | 6.4% | -1 |
| `balanced / no-coarse(global)` | 747 | 13 | 66 | 106 | 3.9% | 0.0% | -3 |
| `balanced / no-onset-snap` | 747 | 22 | 74 | 117 | 4.1% | 0.0% | +20 |
| `balanced / no-weak-rescue` | 747 | 14 | 76 | 128 | 4.4% | 0.0% | -3 |
| `balanced / no-long-note` | 747 | 13 | 66 | 106 | 3.7% | 0.0% | -3 |
| `balanced / anchors-random-5%` | 711 | 14 | 72 | 132 | 4.8% | 0.3% | -3 |
| `balanced / anchors-lowconf-5%` | 711 | 13 | 56 | 87 | 2.3% | 0.0% | -4 |
| `balanced+whisper-attn` | 747 | 35 | 211 | 288 | 17.4% | 0.5% | -4 |
| `balanced+ctc-mms` | 747 | 13 | 55 | 85 | 2.0% | 0.0% | -4 |
| `balanced+qwen` | 747 | 15 | 232 | 403 | 11.0% | 0.0% | -4 |
| `balanced+hybrid` | 747 | 13 | 69 | 107 | 3.6% | 0.0% | -3 |

### zh,10 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 747 | 11 | 54 | 86 | 2.8% | 0.0% | -4 |
| `balanced / no-coarse(regions)` | 747 | 15 | 1340 | 3132 | 21.4% | 6.6% | -3 |
| `balanced / no-coarse(global)` | 747 | 11 | 55 | 88 | 2.9% | 0.0% | -4 |
| `balanced / no-onset-snap` | 747 | 18 | 63 | 101 | 3.1% | 0.0% | +15 |
| `balanced / no-weak-rescue` | 747 | 11 | 58 | 106 | 3.3% | 0.0% | -4 |
| `balanced / no-long-note` | 747 | 11 | 54 | 86 | 2.8% | 0.0% | -4 |
| `balanced / anchors-random-5%` | 711 | 12 | 65 | 128 | 4.2% | 0.0% | -4 |
| `balanced / anchors-lowconf-5%` | 711 | 11 | 49 | 76 | 2.1% | 0.0% | -4 |
| `balanced+whisper-attn` | 747 | 30 | 210 | 287 | 17.8% | 0.9% | -6 |
| `balanced+ctc-mms` | 747 | 11 | 51 | 82 | 2.4% | 0.0% | -5 |
| `balanced+qwen` | 747 | 13 | 289 | 631 | 12.4% | 0.0% | -4 |
| `balanced+hybrid` | 747 | 11 | 55 | 84 | 2.5% | 0.0% | -4 |

### zh,20 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 747 | 8 | 46 | 88 | 3.5% | 0.1% | -4 |
| `balanced / no-coarse(regions)` | 747 | 10 | 871 | 2957 | 17.7% | 5.8% | -3 |
| `balanced / no-coarse(global)` | 747 | 8 | 44 | 79 | 3.6% | 0.0% | -4 |
| `balanced / no-onset-snap` | 747 | 10 | 40 | 101 | 3.6% | 0.1% | +5 |
| `balanced / no-weak-rescue` | 747 | 8 | 50 | 109 | 3.5% | 0.1% | -4 |
| `balanced / no-long-note` | 747 | 8 | 46 | 88 | 3.5% | 0.1% | -4 |
| `balanced / anchors-random-5%` | 711 | 8 | 45 | 78 | 3.1% | 0.1% | -4 |
| `balanced / anchors-lowconf-5%` | 711 | 8 | 41 | 64 | 2.7% | 0.1% | -4 |
| `balanced+whisper-attn` | 747 | 22 | 235 | 309 | 18.6% | 2.4% | -6 |
| `balanced+ctc-mms` | 747 | 7 | 34 | 59 | 2.3% | 0.3% | -4 |
| `balanced+qwen` | 747 | 10 | 383 | 770 | 14.7% | 0.4% | -4 |
| `balanced+hybrid` | 747 | 8 | 46 | 75 | 3.1% | 0.1% | -4 |

### en,0 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 469 | 20 | 107 | 139 | 4.3% | 0.6% | -8 |
| `balanced / no-coarse(regions)` | 469 | 31 | 2969 | 5344 | 22.4% | 8.7% | -6 |
| `balanced / no-coarse(global)` | 469 | 20 | 112 | 156 | 5.3% | 0.6% | -7 |
| `balanced / no-onset-snap` | 469 | 29 | 101 | 131 | 3.8% | 0.6% | +16 |
| `balanced / no-weak-rescue` | 469 | 20 | 110 | 141 | 4.7% | 0.6% | -8 |
| `balanced / no-long-note` | 469 | 20 | 107 | 139 | 4.3% | 0.6% | -8 |
| `balanced / anchors-random-5%` | 447 | 20 | 136 | 365 | 8.9% | 0.7% | -8 |
| `balanced / anchors-lowconf-5%` | 447 | 20 | 141 | 398 | 9.6% | 0.0% | -8 |
| `balanced+whisper-attn` | 469 | 31 | 465 | 781 | 24.1% | 3.0% | -8 |
| `balanced+ctc-mms` | 469 | 15 | 74 | 122 | 3.8% | 1.5% | -6 |
| `balanced+qwen` | 469 | 17 | 117 | 386 | 8.7% | 0.0% | -2 |
| `balanced+hybrid` | 469 | 16 | 82 | 121 | 3.8% | 0.4% | -5 |

### en,5 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 469 | 16 | 103 | 128 | 3.2% | 0.2% | -9 |
| `balanced / no-coarse(regions)` | 469 | 25 | 1952 | 4247 | 19.2% | 6.4% | -8 |
| `balanced / no-coarse(global)` | 469 | 16 | 110 | 136 | 4.1% | 0.6% | -9 |
| `balanced / no-onset-snap` | 469 | 21 | 100 | 117 | 2.6% | 0.2% | +6 |
| `balanced / no-weak-rescue` | 469 | 16 | 107 | 130 | 3.6% | 0.2% | -9 |
| `balanced / no-long-note` | 469 | 16 | 103 | 128 | 3.2% | 0.2% | -9 |
| `balanced / anchors-random-5%` | 447 | 17 | 123 | 194 | 7.2% | 0.0% | -9 |
| `balanced / anchors-lowconf-5%` | 447 | 16 | 114 | 177 | 6.0% | 0.0% | -9 |
| `balanced+whisper-attn` | 469 | 38 | 483 | 769 | 26.2% | 3.0% | -9 |
| `balanced+ctc-mms` | 469 | 12 | 64 | 109 | 4.1% | 1.3% | -7 |
| `balanced+qwen` | 469 | 14 | 144 | 448 | 10.0% | 0.0% | -4 |
| `balanced+hybrid` | 469 | 12 | 58 | 108 | 3.6% | 0.2% | -6 |

### en,10 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 469 | 14 | 115 | 149 | 5.1% | 0.6% | -9 |
| `balanced / no-coarse(regions)` | 469 | 31 | 1347 | 3334 | 19.2% | 5.8% | -8 |
| `balanced / no-coarse(global)` | 469 | 14 | 110 | 132 | 3.4% | 0.0% | -9 |
| `balanced / no-onset-snap` | 469 | 27 | 105 | 125 | 4.3% | 0.6% | +2 |
| `balanced / no-weak-rescue` | 469 | 14 | 115 | 153 | 5.3% | 0.6% | -9 |
| `balanced / no-long-note` | 469 | 14 | 115 | 149 | 5.1% | 0.6% | -9 |
| `balanced / anchors-random-5%` | 447 | 15 | 123 | 174 | 6.9% | 0.4% | -9 |
| `balanced / anchors-lowconf-5%` | 447 | 14 | 119 | 158 | 5.8% | 0.0% | -9 |
| `balanced+whisper-attn` | 469 | 42 | 489 | 819 | 27.7% | 3.4% | -9 |
| `balanced+ctc-mms` | 469 | 10 | 65 | 128 | 4.7% | 2.1% | -7 |
| `balanced+qwen` | 469 | 11 | 134 | 372 | 9.4% | 0.0% | -4 |
| `balanced+hybrid` | 469 | 10 | 65 | 118 | 4.1% | 0.6% | -6 |

### en,20 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 469 | 20 | 120 | 164 | 6.6% | 1.7% | -10 |
| `balanced / no-coarse(regions)` | 469 | 61 | 2032 | 4894 | 22.0% | 6.2% | -8 |
| `balanced / no-coarse(global)` | 469 | 17 | 113 | 145 | 4.5% | 0.0% | -10 |
| `balanced / no-onset-snap` | 469 | 40 | 108 | 135 | 4.7% | 1.7% | -9 |
| `balanced / no-weak-rescue` | 469 | 20 | 120 | 164 | 6.6% | 1.7% | -10 |
| `balanced / no-long-note` | 469 | 20 | 120 | 164 | 6.6% | 1.7% | -10 |
| `balanced / anchors-random-5%` | 447 | 21 | 130 | 195 | 8.7% | 0.2% | -10 |
| `balanced / anchors-lowconf-5%` | 447 | 17 | 124 | 185 | 7.4% | 0.4% | -9 |
| `balanced+whisper-attn` | 469 | 49 | 522 | 850 | 30.7% | 3.8% | -10 |
| `balanced+ctc-mms` | 469 | 9 | 74 | 110 | 3.6% | 1.7% | -7 |
| `balanced+qwen` | 469 | 10 | 285 | 695 | 14.5% | 0.0% | -4 |
| `balanced+hybrid` | 469 | 10 | 92 | 129 | 4.5% | 1.5% | -6 |

### mixed,0 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 654 | 28 | 246 | 515 | 14.1% | 1.7% | -1 |
| `balanced / no-coarse(regions)` | 654 | 76 | 4608 | 5943 | 41.7% | 17.0% | +27 |
| `balanced / no-coarse(global)` | 654 | 30 | 442 | 1409 | 18.3% | 2.8% | -2 |
| `balanced / no-onset-snap` | 654 | 42 | 261 | 566 | 15.4% | 1.7% | +28 |
| `balanced / no-weak-rescue` | 654 | 29 | 263 | 551 | 15.3% | 1.7% | +2 |
| `balanced / no-long-note` | 654 | 28 | 246 | 515 | 14.1% | 1.7% | -1 |
| `balanced / anchors-random-5%` | 621 | 29 | 311 | 590 | 16.6% | 1.9% | +13 |
| `balanced / anchors-lowconf-5%` | 621 | 26 | 188 | 382 | 11.8% | 0.0% | +4 |
| `balanced+whisper-attn` | 654 | 48 | 287 | 653 | 21.1% | 3.1% | +14 |
| `balanced+ctc-mms` | 654 | 24 | 126 | 350 | 9.2% | 2.4% | +4 |
| `balanced+qwen` | 654 | 33 | 596 | 1097 | 21.4% | 1.8% | +28 |
| `balanced+hybrid` | 654 | 27 | 253 | 594 | 12.8% | 1.8% | +18 |

### mixed,5 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 654 | 17 | 142 | 334 | 9.8% | 0.2% | -6 |
| `balanced / no-coarse(regions)` | 654 | 27 | 1727 | 3946 | 25.7% | 7.3% | -5 |
| `balanced / no-coarse(global)` | 654 | 17 | 150 | 340 | 10.1% | 0.6% | -6 |
| `balanced / no-onset-snap` | 654 | 26 | 158 | 307 | 10.6% | 0.2% | +16 |
| `balanced / no-weak-rescue` | 654 | 18 | 156 | 315 | 10.2% | 0.2% | -6 |
| `balanced / no-long-note` | 654 | 17 | 142 | 334 | 9.8% | 0.2% | -6 |
| `balanced / anchors-random-5%` | 621 | 18 | 153 | 358 | 10.3% | 0.2% | -6 |
| `balanced / anchors-lowconf-5%` | 621 | 17 | 128 | 268 | 9.0% | 0.2% | -6 |
| `balanced+whisper-attn` | 654 | 36 | 265 | 563 | 19.1% | 1.7% | -6 |
| `balanced+ctc-mms` | 654 | 16 | 80 | 148 | 4.9% | 0.9% | -6 |
| `balanced+qwen` | 654 | 18 | 363 | 757 | 15.7% | 0.5% | -3 |
| `balanced+hybrid` | 654 | 16 | 91 | 248 | 6.6% | 0.0% | -5 |

### mixed,10 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 654 | 14 | 121 | 302 | 8.7% | 0.5% | -6 |
| `balanced / no-coarse(regions)` | 654 | 19 | 615 | 2126 | 19.3% | 5.7% | -6 |
| `balanced / no-coarse(global)` | 654 | 14 | 110 | 270 | 7.5% | 0.5% | -6 |
| `balanced / no-onset-snap` | 654 | 21 | 137 | 289 | 9.5% | 0.5% | +12 |
| `balanced / no-weak-rescue` | 654 | 14 | 136 | 284 | 9.3% | 0.5% | -6 |
| `balanced / no-long-note` | 654 | 14 | 121 | 302 | 8.7% | 0.5% | -6 |
| `balanced / anchors-random-5%` | 621 | 14 | 115 | 288 | 8.2% | 0.2% | -6 |
| `balanced / anchors-lowconf-5%` | 621 | 14 | 112 | 250 | 7.7% | 0.0% | -6 |
| `balanced+whisper-attn` | 654 | 38 | 272 | 600 | 20.0% | 2.4% | -7 |
| `balanced+ctc-mms` | 654 | 12 | 73 | 139 | 4.6% | 1.4% | -6 |
| `balanced+qwen` | 654 | 15 | 671 | 1277 | 20.3% | 1.2% | -3 |
| `balanced+hybrid` | 654 | 13 | 87 | 222 | 6.4% | 0.5% | -6 |

### mixed,20 dB

| 設定 | tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 654 | 10 | 129 | 651 | 9.3% | 3.1% | -5 |
| `balanced / no-coarse(regions)` | 654 | 13 | 1022 | 3522 | 21.1% | 6.3% | -4 |
| `balanced / no-coarse(global)` | 654 | 10 | 96 | 148 | 5.0% | 0.0% | -6 |
| `balanced / no-onset-snap` | 654 | 12 | 142 | 531 | 9.6% | 3.1% | +4 |
| `balanced / no-weak-rescue` | 654 | 10 | 142 | 521 | 9.6% | 3.1% | -5 |
| `balanced / no-long-note` | 654 | 10 | 129 | 651 | 9.3% | 3.1% | -5 |
| `balanced / anchors-random-5%` | 621 | 10 | 111 | 299 | 8.4% | 0.2% | -6 |
| `balanced / anchors-lowconf-5%` | 621 | 10 | 108 | 294 | 7.6% | 0.2% | -6 |
| `balanced+whisper-attn` | 654 | 37 | 339 | 1074 | 22.8% | 3.8% | -6 |
| `balanced+ctc-mms` | 654 | 9 | 126 | 1416 | 9.5% | 3.8% | -5 |
| `balanced+qwen` | 654 | 12 | 1074 | 2083 | 25.5% | 4.3% | -2 |
| `balanced+hybrid` | 654 | 10 | 136 | 972 | 9.6% | 3.1% | -4 |

## 結束時間(行尾長音)與信心度

| 設定 | 語言 | SNR | 行尾結束誤差中位數 ms | 行尾結束誤差 P90 ms | 信心度 AUROC | 檢查信心最低 10% 找到的問題比例 | 20% |
|---|---|---:|---:|---:|---:|---:|---:|
| `balanced` | zh | 0 dB | 76 | 551 | 0.89 | 58% | 77% |
| `balanced / no-coarse(regions)` | zh | 0 dB | 288 | 4927 | 0.67 | 20% | 35% |
| `balanced / no-coarse(global)` | zh | 0 dB | 84 | 693 | 0.81 | 49% | 67% |
| `balanced / no-onset-snap` | zh | 0 dB | 78 | 552 | 0.89 | 52% | 78% |
| `balanced / no-weak-rescue` | zh | 0 dB | 78 | 552 | 0.88 | 55% | 76% |
| `balanced / no-long-note` | zh | 0 dB | 1040 | 1834 | 0.89 | 58% | 77% |
| `balanced / anchors-random-5%` | zh | 0 dB | 76 | 530 | 0.89 | 57% | 73% |
| `balanced / anchors-lowconf-5%` | zh | 0 dB | 58 | 425 | 0.87 | 63% | 80% |
| `balanced+whisper-attn` | zh | 0 dB | 83 | 1203 | 0.67 | 26% | 38% |
| `balanced+ctc-mms` | zh | 0 dB | 78 | 596 | 0.89 | 59% | 72% |
| `balanced+qwen` | zh | 0 dB | 84 | 552 | 0.91 | 56% | 78% |
| `balanced+hybrid` | zh | 0 dB | 78 | 446 | 0.89 | 60% | 83% |
| `balanced` | zh | 5 dB | 26 | 332 | 0.93 | 71% | 89% |
| `balanced / no-coarse(regions)` | zh | 5 dB | 193 | 4921 | 0.73 | 24% | 43% |
| `balanced / no-coarse(global)` | zh | 5 dB | 28 | 496 | 0.88 | 62% | 72% |
| `balanced / no-onset-snap` | zh | 5 dB | 26 | 254 | 0.94 | 74% | 90% |
| `balanced / no-weak-rescue` | zh | 5 dB | 26 | 254 | 0.94 | 76% | 91% |
| `balanced / no-long-note` | zh | 5 dB | 1044 | 1832 | 0.93 | 71% | 89% |
| `balanced / anchors-random-5%` | zh | 5 dB | 27 | 545 | 0.93 | 68% | 91% |
| `balanced / anchors-lowconf-5%` | zh | 5 dB | 24 | 244 | 0.93 | 75% | 88% |
| `balanced+whisper-attn` | zh | 5 dB | 29 | 397 | 0.65 | 22% | 35% |
| `balanced+ctc-mms` | zh | 5 dB | 26 | 332 | 0.87 | 60% | 80% |
| `balanced+qwen` | zh | 5 dB | 28 | 332 | 0.92 | 56% | 84% |
| `balanced+hybrid` | zh | 5 dB | 26 | 254 | 0.93 | 70% | 81% |
| `balanced` | zh | 10 dB | 18 | 176 | 0.93 | 67% | 90% |
| `balanced / no-coarse(regions)` | zh | 10 dB | 136 | 4918 | 0.74 | 26% | 47% |
| `balanced / no-coarse(global)` | zh | 10 dB | 19 | 193 | 0.86 | 59% | 77% |
| `balanced / no-onset-snap` | zh | 10 dB | 18 | 176 | 0.94 | 70% | 87% |
| `balanced / no-weak-rescue` | zh | 10 dB | 18 | 176 | 0.94 | 72% | 92% |
| `balanced / no-long-note` | zh | 10 dB | 1044 | 1832 | 0.93 | 67% | 90% |
| `balanced / anchors-random-5%` | zh | 10 dB | 19 | 169 | 0.93 | 63% | 87% |
| `balanced / anchors-lowconf-5%` | zh | 10 dB | 18 | 186 | 0.95 | 87% | 93% |
| `balanced+whisper-attn` | zh | 10 dB | 19 | 641 | 0.70 | 29% | 41% |
| `balanced+ctc-mms` | zh | 10 dB | 18 | 193 | 0.77 | 50% | 72% |
| `balanced+qwen` | zh | 10 dB | 18 | 356 | 0.93 | 60% | 85% |
| `balanced+hybrid` | zh | 10 dB | 18 | 176 | 0.92 | 63% | 89% |
| `balanced` | zh | 20 dB | 7 | 121 | 0.91 | 73% | 77% |
| `balanced / no-coarse(regions)` | zh | 20 dB | 12 | 2879 | 0.77 | 29% | 54% |
| `balanced / no-coarse(global)` | zh | 20 dB | 7 | 134 | 0.89 | 56% | 74% |
| `balanced / no-onset-snap` | zh | 20 dB | 7 | 134 | 0.88 | 67% | 74% |
| `balanced / no-weak-rescue` | zh | 20 dB | 7 | 134 | 0.90 | 73% | 77% |
| `balanced / no-long-note` | zh | 20 dB | 1046 | 1832 | 0.91 | 73% | 77% |
| `balanced / anchors-random-5%` | zh | 20 dB | 7 | 136 | 0.92 | 73% | 77% |
| `balanced / anchors-lowconf-5%` | zh | 20 dB | 7 | 108 | 0.94 | 84% | 84% |
| `balanced+whisper-attn` | zh | 20 dB | 7 | 467 | 0.73 | 30% | 44% |
| `balanced+ctc-mms` | zh | 20 dB | 7 | 134 | 0.74 | 29% | 53% |
| `balanced+qwen` | zh | 20 dB | 7 | 439 | 0.92 | 47% | 83% |
| `balanced+hybrid` | zh | 20 dB | 7 | 134 | 0.87 | 61% | 74% |
| `balanced` | en | 0 dB | 273 | 841 | 0.76 | 50% | 60% |
| `balanced / no-coarse(regions)` | en | 0 dB | 433 | 5803 | 0.76 | 31% | 45% |
| `balanced / no-coarse(global)` | en | 0 dB | 288 | 1938 | 0.77 | 40% | 48% |
| `balanced / no-onset-snap` | en | 0 dB | 273 | 1107 | 0.85 | 56% | 78% |
| `balanced / no-weak-rescue` | en | 0 dB | 273 | 1107 | 0.79 | 55% | 64% |
| `balanced / no-long-note` | en | 0 dB | 454 | 1027 | 0.76 | 50% | 60% |
| `balanced / anchors-random-5%` | en | 0 dB | 288 | 1158 | 0.84 | 48% | 78% |
| `balanced / anchors-lowconf-5%` | en | 0 dB | 272 | 1034 | 0.86 | 56% | 77% |
| `balanced+whisper-attn` | en | 0 dB | 363 | 1200 | 0.64 | 19% | 30% |
| `balanced+ctc-mms` | en | 0 dB | 288 | 1105 | 0.77 | 50% | 56% |
| `balanced+qwen` | en | 0 dB | 267 | 841 | 0.94 | 68% | 88% |
| `balanced+hybrid` | en | 0 dB | 273 | 841 | 0.86 | 56% | 67% |
| `balanced` | en | 5 dB | 56 | 798 | 0.75 | 60% | 67% |
| `balanced / no-coarse(regions)` | en | 5 dB | 144 | 4210 | 0.74 | 31% | 48% |
| `balanced / no-coarse(global)` | en | 5 dB | 79 | 798 | 0.77 | 53% | 74% |
| `balanced / no-onset-snap` | en | 5 dB | 56 | 821 | 0.94 | 92% | 92% |
| `balanced / no-weak-rescue` | en | 5 dB | 56 | 821 | 0.78 | 65% | 71% |
| `balanced / no-long-note` | en | 5 dB | 450 | 1104 | 0.75 | 60% | 67% |
| `balanced / anchors-random-5%` | en | 5 dB | 103 | 821 | 0.83 | 56% | 72% |
| `balanced / anchors-lowconf-5%` | en | 5 dB | 54 | 683 | 0.87 | 74% | 78% |
| `balanced+whisper-attn` | en | 5 dB | 158 | 1074 | 0.64 | 19% | 29% |
| `balanced+ctc-mms` | en | 5 dB | 114 | 828 | 0.75 | 47% | 53% |
| `balanced+qwen` | en | 5 dB | 56 | 503 | 0.95 | 74% | 94% |
| `balanced+hybrid` | en | 5 dB | 56 | 798 | 0.89 | 71% | 76% |
| `balanced` | en | 10 dB | 26 | 796 | 0.76 | 58% | 62% |
| `balanced / no-coarse(regions)` | en | 10 dB | 78 | 4534 | 0.72 | 33% | 48% |
| `balanced / no-coarse(global)` | en | 10 dB | 24 | 568 | 0.70 | 50% | 56% |
| `balanced / no-onset-snap` | en | 10 dB | 26 | 796 | 0.89 | 70% | 80% |
| `balanced / no-weak-rescue` | en | 10 dB | 26 | 796 | 0.77 | 60% | 64% |
| `balanced / no-long-note` | en | 10 dB | 476 | 1138 | 0.76 | 58% | 62% |
| `balanced / anchors-random-5%` | en | 10 dB | 30 | 829 | 0.83 | 58% | 65% |
| `balanced / anchors-lowconf-5%` | en | 10 dB | 24 | 803 | 0.78 | 50% | 62% |
| `balanced+whisper-attn` | en | 10 dB | 156 | 1513 | 0.62 | 16% | 27% |
| `balanced+ctc-mms` | en | 10 dB | 36 | 826 | 0.81 | 45% | 68% |
| `balanced+qwen` | en | 10 dB | 26 | 568 | 0.93 | 75% | 86% |
| `balanced+hybrid` | en | 10 dB | 26 | 796 | 0.84 | 58% | 63% |
| `balanced` | en | 20 dB | 12 | 448 | 0.76 | 55% | 71% |
| `balanced / no-coarse(regions)` | en | 20 dB | 13 | 4814 | 0.75 | 30% | 48% |
| `balanced / no-coarse(global)` | en | 20 dB | 11 | 82 | 0.66 | 48% | 48% |
| `balanced / no-onset-snap` | en | 20 dB | 12 | 448 | 0.93 | 77% | 95% |
| `balanced / no-weak-rescue` | en | 20 dB | 12 | 448 | 0.76 | 55% | 71% |
| `balanced / no-long-note` | en | 20 dB | 502 | 1200 | 0.76 | 55% | 71% |
| `balanced / anchors-random-5%` | en | 20 dB | 11 | 237 | 0.78 | 56% | 69% |
| `balanced / anchors-lowconf-5%` | en | 20 dB | 11 | 208 | 0.79 | 58% | 73% |
| `balanced+whisper-attn` | en | 20 dB | 16 | 909 | 0.65 | 17% | 28% |
| `balanced+ctc-mms` | en | 20 dB | 11 | 433 | 0.78 | 53% | 65% |
| `balanced+qwen` | en | 20 dB | 11 | 194 | 0.94 | 51% | 84% |
| `balanced+hybrid` | en | 20 dB | 12 | 448 | 0.89 | 67% | 76% |
| `balanced` | mixed | 0 dB | 113 | 1372 | 0.82 | 35% | 54% |
| `balanced / no-coarse(regions)` | mixed | 0 dB | 976 | 4656 | 0.67 | 17% | 32% |
| `balanced / no-coarse(global)` | mixed | 0 dB | 126 | 1595 | 0.81 | 32% | 57% |
| `balanced / no-onset-snap` | mixed | 0 dB | 122 | 1493 | 0.82 | 33% | 52% |
| `balanced / no-weak-rescue` | mixed | 0 dB | 122 | 1493 | 0.84 | 39% | 57% |
| `balanced / no-long-note` | mixed | 0 dB | 480 | 1578 | 0.82 | 35% | 54% |
| `balanced / anchors-random-5%` | mixed | 0 dB | 122 | 1480 | 0.85 | 38% | 59% |
| `balanced / anchors-lowconf-5%` | mixed | 0 dB | 104 | 1360 | 0.84 | 38% | 58% |
| `balanced+whisper-attn` | mixed | 0 dB | 132 | 1375 | 0.63 | 25% | 41% |
| `balanced+ctc-mms` | mixed | 0 dB | 132 | 1372 | 0.81 | 37% | 53% |
| `balanced+qwen` | mixed | 0 dB | 136 | 789 | 0.91 | 36% | 68% |
| `balanced+hybrid` | mixed | 0 dB | 113 | 837 | 0.87 | 44% | 65% |
| `balanced` | mixed | 5 dB | 23 | 1233 | 0.85 | 42% | 69% |
| `balanced / no-coarse(regions)` | mixed | 5 dB | 77 | 2938 | 0.75 | 22% | 43% |
| `balanced / no-coarse(global)` | mixed | 5 dB | 22 | 902 | 0.90 | 52% | 80% |
| `balanced / no-onset-snap` | mixed | 5 dB | 26 | 1288 | 0.84 | 39% | 61% |
| `balanced / no-weak-rescue` | mixed | 5 dB | 26 | 1288 | 0.86 | 42% | 70% |
| `balanced / no-long-note` | mixed | 5 dB | 406 | 1503 | 0.85 | 42% | 69% |
| `balanced / anchors-random-5%` | mixed | 5 dB | 22 | 1306 | 0.87 | 44% | 73% |
| `balanced / anchors-lowconf-5%` | mixed | 5 dB | 22 | 1258 | 0.86 | 50% | 66% |
| `balanced+whisper-attn` | mixed | 5 dB | 28 | 851 | 0.65 | 26% | 42% |
| `balanced+ctc-mms` | mixed | 5 dB | 22 | 1099 | 0.81 | 44% | 62% |
| `balanced+qwen` | mixed | 5 dB | 23 | 1162 | 0.90 | 47% | 75% |
| `balanced+hybrid` | mixed | 5 dB | 22 | 902 | 0.86 | 60% | 72% |
| `balanced` | mixed | 10 dB | 13 | 900 | 0.81 | 47% | 60% |
| `balanced / no-coarse(regions)` | mixed | 10 dB | 54 | 2255 | 0.76 | 28% | 49% |
| `balanced / no-coarse(global)` | mixed | 10 dB | 14 | 978 | 0.88 | 47% | 78% |
| `balanced / no-onset-snap` | mixed | 10 dB | 14 | 978 | 0.82 | 44% | 60% |
| `balanced / no-weak-rescue` | mixed | 10 dB | 14 | 978 | 0.83 | 48% | 62% |
| `balanced / no-long-note` | mixed | 10 dB | 407 | 1419 | 0.81 | 47% | 60% |
| `balanced / anchors-random-5%` | mixed | 10 dB | 14 | 741 | 0.79 | 43% | 59% |
| `balanced / anchors-lowconf-5%` | mixed | 10 dB | 14 | 876 | 0.82 | 46% | 58% |
| `balanced+whisper-attn` | mixed | 10 dB | 21 | 800 | 0.67 | 24% | 41% |
| `balanced+ctc-mms` | mixed | 10 dB | 14 | 914 | 0.78 | 43% | 63% |
| `balanced+qwen` | mixed | 10 dB | 14 | 531 | 0.93 | 39% | 72% |
| `balanced+hybrid` | mixed | 10 dB | 12 | 379 | 0.82 | 52% | 67% |
| `balanced` | mixed | 20 dB | 10 | 103 | 0.86 | 52% | 74% |
| `balanced / no-coarse(regions)` | mixed | 20 dB | 12 | 3110 | 0.78 | 24% | 46% |
| `balanced / no-coarse(global)` | mixed | 20 dB | 10 | 34 | 0.83 | 33% | 70% |
| `balanced / no-onset-snap` | mixed | 20 dB | 10 | 103 | 0.87 | 56% | 71% |
| `balanced / no-weak-rescue` | mixed | 20 dB | 10 | 103 | 0.87 | 54% | 75% |
| `balanced / no-long-note` | mixed | 20 dB | 526 | 1491 | 0.86 | 52% | 74% |
| `balanced / anchors-random-5%` | mixed | 20 dB | 10 | 44 | 0.81 | 46% | 65% |
| `balanced / anchors-lowconf-5%` | mixed | 20 dB | 10 | 36 | 0.85 | 55% | 68% |
| `balanced+whisper-attn` | mixed | 20 dB | 11 | 393 | 0.73 | 30% | 46% |
| `balanced+ctc-mms` | mixed | 20 dB | 10 | 802 | 0.83 | 40% | 71% |
| `balanced+qwen` | mixed | 20 dB | 11 | 442 | 0.92 | 34% | 60% |
| `balanced+hybrid` | mixed | 20 dB | 10 | 251 | 0.89 | 60% | 76% |

## 處理時間(每分鐘音訊所需秒數,CPU)

| 設定 | ingest | separate | analyze | asr | align | 合計 | 即時倍率 |
|---| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `balanced` | 2.3 | 29.3 | 0.4 | 12.4 | 11.4 | 55.8 | 1.1x |
| `balanced / no-coarse(regions)` | 2.3 | 29.3 | 0.4 | 12.4 | 0.2 | 44.6 | 1.3x |
| `balanced / no-coarse(global)` | 2.3 | 29.3 | 0.4 | 12.4 | 0.2 | 44.6 | 1.3x |
| `balanced / no-onset-snap` | 2.3 | 29.3 | 0.4 | 12.4 | 0.1 | 44.5 | 1.3x |
| `balanced / no-weak-rescue` | 2.3 | 29.3 | 0.4 | 12.4 | 0.1 | 44.5 | 1.3x |
| `balanced / no-long-note` | 2.3 | 29.3 | 0.4 | 12.4 | 0.1 | 44.5 | 1.3x |
| `balanced / anchors-random-5%` | 2.3 | 29.3 | 0.4 | 12.4 | 0.1 | 44.6 | 1.3x |
| `balanced / anchors-lowconf-5%` | 2.3 | 29.3 | 0.4 | 12.4 | 0.1 | 44.6 | 1.3x |
| `balanced+whisper-attn` | 2.3 | 29.3 | 0.4 | 12.4 | 8.6 | 53.0 | 1.1x |
| `balanced+ctc-mms` | 2.3 | 29.3 | 0.4 | 12.4 | 11.7 | 56.1 | 1.1x |
| `balanced+qwen` | 2.3 | 29.3 | 0.4 | 12.4 | 5.2 | 49.6 | 1.2x |
| `balanced+hybrid` | 2.3 | 29.3 | 0.4 | 12.4 | 4.4 | 48.8 | 1.2x |

時間是各階段「實際計算」時記錄下來的秒數;同一首歌的後續設定會沿用分離與辨識的快取,但表中仍列出該階段原本的計算時間。

