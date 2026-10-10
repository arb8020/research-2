| rule                               | dtype   | ops                         | correct_falsefail   | grey_fail   | subtle_detect   | bug_detect   |
|:-----------------------------------|:--------|:----------------------------|:--------------------|:------------|:----------------|:-------------|
| old 2x                             | fp32    | linear,pv,qk                | 0%                  | 0%          | 100%            | 100%         |
| old 2x                             | fp16    | linear,pv,qk                | 1%                  | 37%         | 100%            | 100%         |
| old 2x                             | bf16    | linear,pv,qk                | 0%                  | 27%         | nan%            | 98%          |
| BLAS r>k (planned)                 | fp32    | linear,pv,qk                | 0%                  | 0%          | 100%            | 100%         |
| BLAS r>k (planned)                 | fp16    | linear,pv,qk                | 2%                  | 62%         | 57%             | 84%          |
| BLAS r>k (planned)                 | bf16    | linear,pv,qk                | 6%                  | 58%         | nan%            | 78%          |
| BLAS r>sqrt(k) (warn)              | fp32    | linear,pv,qk                | 0%                  | 0%          | 100%            | 100%         |
| BLAS r>sqrt(k) (warn)              | fp16    | linear,pv,qk                | 10%                 | 65%         | 67%             | 95%          |
| BLAS r>sqrt(k) (warn)              | bf16    | linear,pv,qk                | 10%                 | 65%         | nan%            | 99%          |
| split gauge (k on acc term only)   | fp32    | linear,pv,qk                | 0%                  | 0%          | 100%            | 100%         |
| split gauge (k on acc term only)   | fp16    | linear,pv,qk                | 0%                  | 62%         | 100%            | 100%         |
| split gauge (k on acc term only)   | bf16    | linear,pv,qk                | 0%                  | 62%         | nan%            | 100%         |
| old 2x                             | fp32    | gelu                        | 0%                  | nan%        | 42%             | 100%         |
| old 2x                             | fp16    | gelu                        | 0%                  | nan%        | 0%              | 50%          |
| old 2x                             | bf16    | gelu                        | 0%                  | nan%        | 0%              | 50%          |
| gelu gauge planned (floor=u)       | fp32    | gelu                        | 0%                  | nan%        | 82%             | 100%         |
| gelu gauge planned (floor=u)       | fp16    | gelu                        | 0%                  | nan%        | 0%              | 50%          |
| gelu gauge planned (floor=u)       | bf16    | gelu                        | 0%                  | nan%        | 0%              | 50%          |
| gelu gauge +u|x|                   | fp32    | gelu                        | 0%                  | nan%        | 75%             | 100%         |
| gelu gauge +u|x|                   | fp16    | gelu                        | 0%                  | nan%        | 0%              | 50%          |
| gelu gauge +u|x|                   | bf16    | gelu                        | 0%                  | nan%        | 0%              | 50%          |
| MCA rms (gelu)                     | fp32    | gelu                        | 0%                  | nan%        | 100%            | 100%         |
| MCA rms (gelu)                     | fp16    | gelu                        | 0%                  | nan%        | 0%              | 50%          |
| MCA rms (gelu)                     | bf16    | gelu                        | 0%                  | nan%        | 0%              | 50%          |
| old 2x                             | fp32    | attention,layernorm,softmax | 1%                  | 8%          | 60%             | 100%         |
| old 2x                             | fp16    | attention,layernorm,softmax | 21%                 | 60%         | 65%             | 95%          |
| old 2x                             | bf16    | attention,layernorm,softmax | 13%                 | 27%         | 31%             | 89%          |
| MCA rms, pairwise, c=1             | fp32    | attention,layernorm,softmax | 29%                 | 25%         | 73%             | 100%         |
| MCA rms, pairwise, c=1             | fp16    | attention,layernorm,softmax | 14%                 | 40%         | 30%             | 100%         |
| MCA rms, pairwise, c=1             | bf16    | attention,layernorm,softmax | 7%                  | 25%         | 0%              | 99%          |
| MCA max, pairwise, c=1             | fp32    | attention,layernorm,softmax | 26%                 | 25%         | 73%             | 100%         |
| MCA max, pairwise, c=1             | fp16    | attention,layernorm,softmax | 9%                  | 42%         | 24%             | 100%         |
| MCA max, pairwise, c=1             | bf16    | attention,layernorm,softmax | 8%                  | 25%         | 0%              | 100%         |
| MCA rms, sequential, c=1           | fp32    | attention,layernorm,softmax | 3%                  | 8%          | 73%             | 100%         |
| MCA rms, sequential, c=1           | fp16    | attention,layernorm,softmax | 5%                  | 25%         | 8%              | 100%         |
| MCA rms, sequential, c=1           | bf16    | attention,layernorm,softmax | 2%                  | 8%          | 0%              | 95%          |
| MCA rms, sequential, c=2           | fp32    | attention,layernorm,softmax | 0%                  | 8%          | 67%             | 100%         |
| MCA rms, sequential, c=2           | fp16    | attention,layernorm,softmax | 2%                  | 25%         | 3%              | 97%          |
| MCA rms, sequential, c=2           | bf16    | attention,layernorm,softmax | 0%                  | 8%          | 0%              | 83%          |
| MCA max, sequential, c=2           | fp32    | attention,layernorm,softmax | 1%                  | 8%          | 70%             | 100%         |
| MCA max, sequential, c=2           | fp16    | attention,layernorm,softmax | 3%                  | 25%         | 6%              | 100%         |
| MCA max, sequential, c=2           | bf16    | attention,layernorm,softmax | 1%                  | 8%          | 0%              | 87%          |
| MCA rms, fp32-opmath contract, c=2 | fp32    | attention,layernorm,softmax | 7%                  | 18%         | 73%             | 100%         |
| MCA rms, fp32-opmath contract, c=2 | fp16    | attention,layernorm,softmax | 39%                 | 67%         | 80%             | 100%         |
| MCA rms, fp32-opmath contract, c=2 | bf16    | attention,layernorm,softmax | 36%                 | 50%         | 80%             | 99%          |
