// The seam between the page's connected session (the Connect UI and its kernel client) and widgets that run
// code on it, like <nn-fit>'s remote backend. The connect client publishes a RemoteRunner when a session is
// connected and null when it goes away; widgets read the current one and subscribe to changes.
//
// It lives on `window`, not in module state: page.ts and each embed's element.ts are separate esbuild bundles,
// so each would get its own copy of a module-level variable.
//
// Wiring (the connect client, once its kernel client exists):
//   setRemoteRunner({ label: "Modal · T4", run: (code, onStdout) => kernel.runCode(code, onStdout), interrupt: () => kernel.interrupt() });
//   setRemoteRunner(null);   // on disconnect

export interface RemoteRunner {
  readonly label: string; // where code runs, for the reader: "Modal · T4"
  // Run `code` (Python) to completion. onStdout gets stdout as it arrives, in chunks that need not end on line
  // boundaries. Resolves when the code finishes, whether it raised or not; rejects only if the session failed.
  run(code: string, onStdout: (text: string) => void): Promise<RunResult>;
  // Ask the running code to stop (a KeyboardInterrupt / SIGINT in the kernel). Resolves once it is sent.
  interrupt(): Promise<void>;
}

export type RunResult = { readonly ok: true } | { readonly ok: false; readonly error: string };

const CHANGE = "remote-runner-change";

declare global {
  interface Window {
    blogsRemoteRunner?: RemoteRunner | null;
  }
}

export function remoteRunner(): RemoteRunner | null {
  return window.blogsRemoteRunner ?? null;
}

export function setRemoteRunner(runner: RemoteRunner | null): void {
  window.blogsRemoteRunner = runner;
  window.dispatchEvent(new Event(CHANGE));
}

// Calls `fn` whenever the runner is set or cleared; returns the unsubscribe.
export function onRemoteRunnerChange(fn: () => void): () => void {
  window.addEventListener(CHANGE, fn);
  return () => { window.removeEventListener(CHANGE, fn); };
}
