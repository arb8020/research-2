import { LineSplitter, hits, registerFileViews } from "./out-links";

function check(ok: boolean, message: string): void {
  if (!ok) throw new Error(`FAIL ${message}`);
  console.log(`ok   ${message}`);
}

registerFileViews("ring.cpp", () => { throw new Error("jumping is not tested here"); });
const links = (line: string): string[] => hits(line).map((h) => `${h.path}:${String(h.line)}:${String(h.col)}`);

check(links("/root/_blogs/tree/ring.cpp:12:5: error: expected ';'").join() === "ring.cpp:12:5", "an absolute sandbox path links to the workspace file by its suffix");
check(links("ring.cpp:3: warning").join() === "ring.cpp:3:1", "a relative path (make) links too");
check(links("make: *** [Makefile:22: ring] Error 1").length === 0, "Makefile:22 stays text");
check(links("0x602000000010:1 is located 0 bytes after").length === 0, "an address like 0x6020...:1 stays text");
const seen: string[] = [];
const splitter = new LineSplitter((line) => { seen.push(line); });
splitter.feed("ring.cpp:");
check(seen.length === 0, "only complete lines are linkified: a chunk without its newline waits");
splitter.feed("7: error\nring");
splitter.end();
check(seen.join("|") === "ring.cpp:7: error|ring", "the tail arrives at its newline or the end");
