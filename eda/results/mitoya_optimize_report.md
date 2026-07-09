# みとや大森町 推薦重み最適化

## Stage Results

| stage     | lift@10_A | lift@10_B | lift@10_avg |
| --------- | --------- | --------- | ----------- |
| stage1    | 289.79    | 216.34    | 253.06      |
| stage2    | 289.40    | 217.95    | 253.67      |
| stage3    | 289.98    | 220.73    | 255.36      |
| fine_tune | 291.25    | 219.63    | 255.44      |

## Current vs Optimized

| label     | section_baseline_scale | h_jug_corner1 | h_jug_corner24 | h_jug_corner59 | h_jug_xdds | h_jug_section_641_657 | h_jug_section_675_691 | h_jug_section_658_674 | h_nonjug_xdds | h_nonjug_corner1_xdds | h_nonjug_corner1_nonevent_penalty | dd24_boost | v_jug_xdds | v_jug_section_723_733 | v_jug_section_734_744 | v_jug_section_712_722 | mixed_805_debut_xdds | mixed_805_growth_xdds_penalty |
| --------- | ---------------------- | ------------- | -------------- | -------------- | ---------- | --------------------- | --------------------- | --------------------- | ------------- | --------------------- | --------------------------------- | ---------- | ---------- | --------------------- | --------------------- | --------------------- | -------------------- | ----------------------------- |
| current   | 0.100                  | 400.00        | 150.00         | 30.000         | 100.00     | 80.000                | 40.000                | 10.000                | 200.00        | 300.00                | -100.00                           | 500.00     | 100.00     | 20.000                | 10.000                | 5.000                 | 300.00               | -100.00                       |
| optimized | 0.000                  | 500.00        | 250.00         | 0.000          | 100.00     | 80.000                | 40.000                | 10.000                | 300.00        | 300.00                | -100.00                           | 200.00     | 100.00     | 20.000                | 10.000                | 5.000                 | 300.00               | -100.00                       |

## Grid Preview

| stage  | param_name                                  | param_value                                                         | lift@10_A | lift@10_B | lift@10_avg |
| ------ | ------------------------------------------- | ------------------------------------------------------------------- | --------- | --------- | ----------- |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 50, "h_jug_corner59": 0}   | 272.81    | 206.91    | 239.86      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 50, "h_jug_corner59": 15}  | 265.51    | 213.15    | 239.33      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 50, "h_jug_corner59": 30}  | 267.06    | 204.63    | 235.85      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 50, "h_jug_corner59": 50}  | 268.37    | 204.51    | 236.44      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 100, "h_jug_corner59": 0}  | 286.06    | 208.67    | 247.36      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 100, "h_jug_corner59": 15} | 281.96    | 208.14    | 245.05      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 100, "h_jug_corner59": 30} | 274.65    | 206.02    | 240.33      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 100, "h_jug_corner59": 50} | 268.83    | 209.50    | 239.16      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 150, "h_jug_corner59": 0}  | 289.04    | 207.21    | 248.13      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 150, "h_jug_corner59": 15} | 287.54    | 207.08    | 247.31      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 150, "h_jug_corner59": 30} | 284.65    | 204.65    | 244.65      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 150, "h_jug_corner59": 50} | 281.54    | 209.40    | 245.47      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 200, "h_jug_corner59": 0}  | 232.67    | 176.60    | 204.64      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 200, "h_jug_corner59": 15} | 231.17    | 176.47    | 203.82      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 200, "h_jug_corner59": 30} | 228.29    | 174.04    | 201.16      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 200, "h_jug_corner59": 50} | 225.17    | 178.75    | 201.96      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 250, "h_jug_corner59": 0}  | 211.97    | 171.62    | 191.79      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 250, "h_jug_corner59": 15} | 210.47    | 171.49    | 190.98      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 250, "h_jug_corner59": 30} | 207.58    | 169.06    | 188.32      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 200, "h_jug_corner24": 250, "h_jug_corner59": 50} | 204.47    | 173.77    | 189.12      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 300, "h_jug_corner24": 50, "h_jug_corner59": 0}   | 272.75    | 207.31    | 240.03      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 300, "h_jug_corner24": 50, "h_jug_corner59": 15}  | 265.45    | 213.54    | 239.49      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 300, "h_jug_corner24": 50, "h_jug_corner59": 30}  | 267.00    | 205.03    | 236.01      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 300, "h_jug_corner24": 50, "h_jug_corner59": 50}  | 268.30    | 204.90    | 236.60      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 300, "h_jug_corner24": 100, "h_jug_corner59": 0}  | 286.00    | 209.06    | 247.53      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 300, "h_jug_corner24": 100, "h_jug_corner59": 15} | 281.89    | 208.53    | 245.21      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 300, "h_jug_corner24": 100, "h_jug_corner59": 30} | 274.58    | 206.41    | 240.50      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 300, "h_jug_corner24": 100, "h_jug_corner59": 50} | 268.76    | 209.90    | 239.33      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 300, "h_jug_corner24": 150, "h_jug_corner59": 0}  | 285.99    | 206.99    | 246.49      |
| stage1 | h_jug_corner1,h_jug_corner24,h_jug_corner59 | {"h_jug_corner1": 300, "h_jug_corner24": 150, "h_jug_corner59": 15} | 284.49    | 206.86    | 245.67      |
