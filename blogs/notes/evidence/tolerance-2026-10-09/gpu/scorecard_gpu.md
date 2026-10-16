# scorecard: CPU (original run) vs T4 vs L4

false-fail on correct / held-out (GPU only) / grey fail / subtle detect / bug detect

| dev   | rule                                   | dtype   | correct_ff   | heldout_ff   | grey_fail   | subtle_det   | bug_det   |
|:------|:---------------------------------------|:--------|:-------------|:-------------|:------------|:-------------|:----------|
| CPU   | old 2x [contractions]                  | fp32    | 0%           | -            | 0%          | 100%         | 100%      |
| CPU   | old 2x [contractions]                  | fp16    | 1%           | -            | 37%         | 100%         | 100%      |
| CPU   | old 2x [contractions]                  | bf16    | 0%           | -            | 27%         | -            | 98%       |
| CPU   | split gauge [contractions]             | fp32    | 0%           | -            | 0%          | 100%         | 100%      |
| CPU   | split gauge [contractions]             | fp16    | 0%           | -            | 62%         | 100%         | 100%      |
| CPU   | split gauge [contractions]             | bf16    | 0%           | -            | 62%         | -            | 100%      |
| CPU   | MCA rms c=1 [gelu]                     | fp32    | 0%           | -            | -           | 100%         | 100%      |
| CPU   | MCA rms c=1 [gelu]                     | fp16    | 0%           | -            | -           | 0%           | 50%       |
| CPU   | MCA rms c=1 [gelu]                     | bf16    | 0%           | -            | -           | 0%           | 50%       |
| CPU   | gelu gauge +u|x| [gelu]                | fp32    | 0%           | -            | -           | 75%          | 100%      |
| CPU   | gelu gauge +u|x| [gelu]                | fp16    | 0%           | -            | -           | 0%           | 50%       |
| CPU   | gelu gauge +u|x| [gelu]                | bf16    | 0%           | -            | -           | 0%           | 50%       |
| CPU   | old 2x [LN,sm,attn]                    | fp32    | 1%           | -            | 8%          | 60%          | 100%      |
| CPU   | old 2x [LN,sm,attn]                    | fp16    | 21%          | -            | 60%         | 65%          | 95%       |
| CPU   | old 2x [LN,sm,attn]                    | bf16    | 13%          | -            | 27%         | 31%          | 89%       |
| CPU   | MCA rms pairwise K64 c=2               | fp32    | 7%           | -            | 18%         | 73%          | 100%      |
| CPU   | MCA rms pairwise K64 c=2               | fp16    | 8%           | -            | 32%         | 14%          | 100%      |
| CPU   | MCA rms pairwise K64 c=2               | bf16    | 6%           | -            | 12%         | 0%           | 94%       |
| CPU   | MCA rms seq K32 c=2                    | fp32    | 0%           | -            | 8%          | 67%          | 100%      |
| CPU   | MCA rms seq K32 c=2                    | fp16    | 2%           | -            | 25%         | 3%           | 97%       |
| CPU   | MCA rms seq K32 c=2                    | bf16    | 0%           | -            | 8%          | 0%           | 83%       |
| CPU   | MCA max seq K32 c=2                    | fp32    | 1%           | -            | 8%          | 70%          | 100%      |
| CPU   | MCA max seq K32 c=2                    | fp16    | 3%           | -            | 25%         | 6%           | 100%      |
| CPU   | MCA max seq K32 c=2                    | bf16    | 1%           | -            | 8%          | 0%           | 87%       |
| CPU   | MCA rms pairwise K64 c=2, --inner fp32 | fp32    | 7%           | -            | 18%         | 73%          | 100%      |
| CPU   | MCA rms pairwise K64 c=2, --inner fp32 | fp16    | 39%          | -            | 67%         | 80%          | 100%      |
| CPU   | MCA rms pairwise K64 c=2, --inner fp32 | bf16    | 36%          | -            | 50%         | 80%          | 99%       |
| T4    | old 2x [contractions]                  | fp32    | 1%           | 0%           | 0%          | 100%         | 100%      |
| T4    | old 2x [contractions]                  | fp16    | 1%           | 1%           | 37%         | 100%         | 100%      |
| T4    | old 2x [contractions]                  | bf16    | 0%           | 0%           | 27%         | -            | 98%       |
| T4    | split gauge [contractions]             | fp32    | 0%           | 0%           | 0%          | 100%         | 100%      |
| T4    | split gauge [contractions]             | fp16    | 0%           | 0%           | 62%         | 100%         | 100%      |
| T4    | split gauge [contractions]             | bf16    | 0%           | 0%           | 62%         | -            | 100%      |
| T4    | MCA rms c=1 [gelu]                     | fp32    | 0%           | 4%           | -           | 100%         | 100%      |
| T4    | MCA rms c=1 [gelu]                     | fp16    | 0%           | 0%           | -           | 0%           | 50%       |
| T4    | MCA rms c=1 [gelu]                     | bf16    | 0%           | 0%           | -           | 0%           | 50%       |
| T4    | gelu gauge +u|x| [gelu]                | fp32    | 0%           | 0%           | -           | 75%          | 100%      |
| T4    | gelu gauge +u|x| [gelu]                | fp16    | 0%           | 0%           | -           | 0%           | 50%       |
| T4    | gelu gauge +u|x| [gelu]                | bf16    | 0%           | 0%           | -           | 0%           | 50%       |
| T4    | old 2x [LN,sm,attn]                    | fp32    | 0%           | 1%           | 8%          | 60%          | 100%      |
| T4    | old 2x [LN,sm,attn]                    | fp16    | 21%          | 3%           | 53%         | 65%          | 95%       |
| T4    | old 2x [LN,sm,attn]                    | bf16    | 12%          | 7%           | 27%         | 31%          | 89%       |
| T4    | MCA rms pairwise K64 c=2               | fp32    | 7%           | 0%           | 17%         | 73%          | 100%      |
| T4    | MCA rms pairwise K64 c=2               | fp16    | 8%           | 0%           | 32%         | 13%          | 100%      |
| T4    | MCA rms pairwise K64 c=2               | bf16    | 6%           | 0%           | 13%         | 0%           | 93%       |
| T4    | MCA rms seq K32 c=2                    | fp32    | 0%           | 0%           | 8%          | 67%          | 100%      |
| T4    | MCA rms seq K32 c=2                    | fp16    | 2%           | 0%           | 25%         | 3%           | 97%       |
| T4    | MCA rms seq K32 c=2                    | bf16    | 0%           | 0%           | 8%          | 0%           | 84%       |
| T4    | MCA max seq K32 c=2                    | fp32    | 1%           | 0%           | 8%          | 70%          | 100%      |
| T4    | MCA max seq K32 c=2                    | fp16    | 3%           | 0%           | 25%         | 3%           | 99%       |
| T4    | MCA max seq K32 c=2                    | bf16    | 1%           | 0%           | 8%          | 0%           | 91%       |
| T4    | MCA rms seq K16 c=2 (recommended)      | fp32    | 0%           | 0%           | 8%          | 67%          | 100%      |
| T4    | MCA rms seq K16 c=2 (recommended)      | fp16    | 2%           | 0%           | 25%         | 3%           | 97%       |
| T4    | MCA rms seq K16 c=2 (recommended)      | bf16    | 0%           | 0%           | 8%          | 0%           | 83%       |
| T4    | MCA rms pairwise K64 c=2, --inner fp32 | fp32    | 7%           | 0%           | 17%         | 73%          | 100%      |
| T4    | MCA rms pairwise K64 c=2, --inner fp32 | fp16    | 39%          | 9%           | 67%         | 80%          | 100%      |
| T4    | MCA rms pairwise K64 c=2, --inner fp32 | bf16    | 36%          | 26%          | 50%         | 80%          | 99%       |
| T4    | MCA rms seq K16 c=2, --inner fp32      | fp32    | 0%           | 0%           | 8%          | 67%          | 100%      |
| T4    | MCA rms seq K16 c=2, --inner fp32      | fp16    | 39%          | 9%           | 67%         | 80%          | 100%      |
| T4    | MCA rms seq K16 c=2, --inner fp32      | bf16    | 36%          | 26%          | 50%         | 80%          | 99%       |
| L4    | old 2x [contractions]                  | fp32    | 0%           | 0%           | 60%         | 100%         | 100%      |
| L4    | old 2x [contractions]                  | fp16    | 1%           | 1%           | 37%         | 100%         | 100%      |
| L4    | old 2x [contractions]                  | bf16    | 0%           | 0%           | 27%         | -            | 98%       |
| L4    | split gauge [contractions]             | fp32    | 0%           | 0%           | 60%         | 100%         | 100%      |
| L4    | split gauge [contractions]             | fp16    | 0%           | 0%           | 62%         | 100%         | 100%      |
| L4    | split gauge [contractions]             | bf16    | 0%           | 0%           | 62%         | -            | 100%      |
| L4    | MCA rms c=1 [gelu]                     | fp32    | 0%           | 4%           | -           | 100%         | 100%      |
| L4    | MCA rms c=1 [gelu]                     | fp16    | 0%           | 0%           | -           | 0%           | 50%       |
| L4    | MCA rms c=1 [gelu]                     | bf16    | 0%           | 0%           | -           | 0%           | 50%       |
| L4    | gelu gauge +u|x| [gelu]                | fp32    | 0%           | 0%           | -           | 75%          | 100%      |
| L4    | gelu gauge +u|x| [gelu]                | fp16    | 0%           | 0%           | -           | 0%           | 50%       |
| L4    | gelu gauge +u|x| [gelu]                | bf16    | 0%           | 0%           | -           | 0%           | 50%       |
| L4    | old 2x [LN,sm,attn]                    | fp32    | 0%           | 7%           | 8%          | 60%          | 100%      |
| L4    | old 2x [LN,sm,attn]                    | fp16    | 21%          | 3%           | 53%         | 65%          | 95%       |
| L4    | old 2x [LN,sm,attn]                    | bf16    | 12%          | 2%           | 27%         | 31%          | 89%       |
| L4    | MCA rms pairwise K64 c=2               | fp32    | 6%           | 11%          | 17%         | 73%          | 100%      |
| L4    | MCA rms pairwise K64 c=2               | fp16    | 8%           | 0%           | 32%         | 14%          | 100%      |
| L4    | MCA rms pairwise K64 c=2               | bf16    | 6%           | 0%           | 13%         | 0%           | 93%       |
| L4    | MCA rms seq K32 c=2                    | fp32    | 0%           | 10%          | 8%          | 67%          | 100%      |
| L4    | MCA rms seq K32 c=2                    | fp16    | 2%           | 0%           | 25%         | 3%           | 97%       |
| L4    | MCA rms seq K32 c=2                    | bf16    | 0%           | 0%           | 8%          | 0%           | 83%       |
| L4    | MCA max seq K32 c=2                    | fp32    | 1%           | 7%           | 8%          | 69%          | 100%      |
| L4    | MCA max seq K32 c=2                    | fp16    | 3%           | 0%           | 25%         | 4%           | 99%       |
| L4    | MCA max seq K32 c=2                    | bf16    | 1%           | 0%           | 8%          | 0%           | 91%       |
| L4    | MCA rms seq K16 c=2 (recommended)      | fp32    | 0%           | 9%           | 8%          | 67%          | 100%      |
| L4    | MCA rms seq K16 c=2 (recommended)      | fp16    | 2%           | 0%           | 25%         | 3%           | 97%       |
| L4    | MCA rms seq K16 c=2 (recommended)      | bf16    | 0%           | 0%           | 8%          | 0%           | 83%       |
| L4    | MCA rms pairwise K64 c=2, --inner fp32 | fp32    | 6%           | 11%          | 17%         | 73%          | 100%      |
| L4    | MCA rms pairwise K64 c=2, --inner fp32 | fp16    | 39%          | 13%          | 67%         | 80%          | 100%      |
| L4    | MCA rms pairwise K64 c=2, --inner fp32 | bf16    | 36%          | 11%          | 50%         | 80%          | 99%       |
| L4    | MCA rms seq K16 c=2, --inner fp32      | fp32    | 0%           | 9%           | 8%          | 67%          | 100%      |
| L4    | MCA rms seq K16 c=2, --inner fp32      | fp16    | 39%          | 10%          | 67%         | 80%          | 100%      |
| L4    | MCA rms seq K16 c=2, --inner fp32      | bf16    | 36%          | 11%          | 50%         | 80%          | 99%       |