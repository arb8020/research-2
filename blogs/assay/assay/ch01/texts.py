"""Fixed text for the measurement prompts. Prose is public domain (Dickens, Lincoln, Melville, Austen)."""

TWO_CITIES = (
    "It was the best of times, it was the worst of times, it was the age of wisdom, it was the age of "
    "foolishness, it was the epoch of belief, it was the epoch of incredulity, it was the season of Light, "
    "it was the season of Darkness, it was the spring of hope, it was the winter of despair, we had "
    "everything before us, we had nothing before us, we were all going direct to Heaven, we were all going "
    "direct the other way--in short, the period was so far like the present period, that some of its "
    "noisiest authorities insisted on its being received, for good or for evil, in the superlative degree "
    "of comparison only.\n\n"
)

GETTYSBURG = (
    "Four score and seven years ago our fathers brought forth on this continent, a new nation, conceived in "
    "Liberty, and dedicated to the proposition that all men are created equal. Now we are engaged in a great "
    "civil war, testing whether that nation, or any nation so conceived and so dedicated, can long endure. "
    "We are met on a great battle-field of that war. We have come to dedicate a portion of that field, as a "
    "final resting place for those who here gave their lives that that nation might live. It is altogether "
    "fitting and proper that we should do this. But, in a larger sense, we can not dedicate--we can not "
    "consecrate--we can not hallow--this ground. The brave men, living and dead, who struggled here, have "
    "consecrated it, far above our poor power to add or detract. The world will little note, nor long "
    "remember what we say here, but it can never forget what they did here. It is for us the living, rather, "
    "to be dedicated here to the unfinished work which they who fought here have thus far so nobly advanced. "
    "It is rather for us to be here dedicated to the great task remaining before us--that from these honored "
    "dead we take increased devotion to that cause for which they gave the last full measure of devotion--"
    "that we here highly resolve that these dead shall not have died in vain--that this nation, under God, "
    "shall have a new birth of freedom--and that government of the people, by the people, for the people, "
    "shall not perish from the earth.\n\n"
)

MOBY_DICK = (
    "Call me Ishmael. Some years ago--never mind how long precisely--having little or no money in my purse, "
    "and nothing particular to interest me on shore, I thought I would sail about a little and see the "
    "watery part of the world. It is a way I have of driving off the spleen and regulating the circulation. "
    "Whenever I find myself growing grim about the mouth; whenever it is a damp, drizzly November in my soul; "
    "whenever I find myself involuntarily pausing before coffin warehouses, and bringing up the rear of every "
    "funeral I meet; and especially whenever my hypos get such an upper hand of me, that it requires a strong "
    "moral principle to prevent me from deliberately stepping into the street, and methodically knocking "
    "people's hats off--then, I account it high time to get to sea as soon as I can. This is my substitute "
    "for pistol and ball. With a philosophical flourish Cato throws himself upon his sword; I quietly take "
    "to the ship. There is nothing surprising in this. If they but knew it, almost all men in their degree, "
    "some time or other, cherish very nearly the same feelings towards the ocean with me.\n\n"
)

PRIDE = (
    "It is a truth universally acknowledged, that a single man in possession of a good fortune, must be in "
    "want of a wife. However little known the feelings or views of such a man may be on his first entering "
    "a neighbourhood, this truth is so well fixed in the minds of the surrounding families, that he is "
    "considered the rightful property of some one or other of their daughters. \"My dear Mr. Bennet,\" said "
    "his lady to him one day, \"have you heard that Netherfield Park is let at last?\" Mr. Bennet replied "
    "that he had not. \"But it is,\" returned she; \"for Mrs. Long has just been here, and she told me all "
    "about it.\" Mr. Bennet made no answer. \"Do you not want to know who has taken it?\" cried his wife "
    "impatiently. \"You want to tell me, and I have no objection to hearing it.\" This was invitation "
    "enough.\n\n"
)

CODE = '''def fib(n: int) -> int:
    """Return the n-th Fibonacci number."""
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


if __name__ == "__main__":
    for i in range(10):
        print(i, fib(i))
'''

UNICODE = "Café naïve façade — “smart quotes” 日本語のテキスト 🤖🚀 Ελληνικά, русский, عربي. ∑∫√ ≠ ≈"

# Perplexity text: Moby-Dick's opening (~250 tokens). Not in any prompt other than near_limit.
PERPLEXITY = MOBY_DICK

# Long text for the near-limit prompts; tokenized and cut to an exact token count by the harness.
LONG = TWO_CITIES + GETTYSBURG + PRIDE + CODE + "\n" + MOBY_DICK + UNICODE + "\n\n" + GETTYSBURG
