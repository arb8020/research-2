# BetterExplained: Intuitive Arithmetic With Complex Numbers

Source: https://betterexplained.com/articles/intuitive-arithmetic-with-complex-numbers/ (Kalid Azad). Siblings read: the imaginary-numbers intro and the interactive Fourier guide.

## Distillation
- Static WordPress page. Equations are mostly old pre-rendered LaTeX PNGs, plus some MathJax 3. Seven static diagrams. **No interactivity at all** in this article; the reader computes by hand.
- **Thesis and map first.** Line one is the big idea ("they rotate numbers, like negatives mirror them"). Then a cheatsheet table, "Complex Operation | Intuitive Meaning", covering every operation. The rest of the article explains it row by row.
- **Each new idea tied to an old one**: two-part number ~ mixed number; |z| ~ absolute value; addition = "sliding"; subtraction/division = "the opposite" of earlier ops. It says where an analogy breaks.
- **Easy to hard, each step setting up the next.** Division is deliberately left stuck ("Hrm. Where to start?") so conjugates arrive as the fix, then the division payoff.
- **Predict, compute, check** is the main technique. Before squaring 3+4i it predicts magnitude 25 and an angle above 90°, then does the algebra and confirms both. Intuition becomes a way to catch mistakes.
- **Two methods side by side**: intuitive (rotate/rescale) vs textbook (multiply by conjugate), then the textbook route reread in intuitive terms; each checks the other.
- **Intuition first, algebra optional and clearly marked** ("The math fans can try the algebra", "Curious? ...", "save it for another time").
- **Names the reader's confusion out loud**, often with humour ("Dividing regular algebraic numbers gives me the creeps").
- **Notation after the idea** ("distance from zero", then |z|), plus heading off a misreading of the notation.
- **One running example** (3+4i, a 3-4-5 triangle) reused throughout, so arithmetic stays checkable in your head.
- Participation is only implied: invitations to predict, try, "see for yourself". No exercises or answer checks.
- **Fourier sibling** does have interactivity: one small jQuery/canvas widget embedded several times via iframe, each preset by URL params (`?cycles=0,1`). Cheap way to give every section its own live example. It also embeds a now-dead Flash iframe.
- A series nav at the bottom (12 links) places the article in a learning path.

## Relevance to the series
- "Predict, compute, check" maps naturally onto gated cells: ask the reader what a gradient/return should look like before running it.
- A cheatsheet/map at the top of each chapter (e.g. naive policy gradient → baseline → advantage → clipping) gives the "explain it row by row" structure.
- Hit-a-wall-then-fix structure is good for motivating baselines and PPO clipping.
- One running example per chapter (e.g. one flappy env config) keeps numbers checkable.
- The URL-preset embedded widget is a cheap pattern for reusing the wasm play widget across sections.
- Warning: the dead Flash embed shows embedded tech rots; this article's text-only core aged fine.

## Caveats from the report
- Fetched with curl, rendered page not seen; only the cheatsheet image was viewed. Publish date not found (probably late 2000s).

source: subagent file agent-a2bf44f7c4f410150.jsonl
